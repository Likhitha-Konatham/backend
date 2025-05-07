from datetime import datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form, Request
from bson import ObjectId
from auth.jwt_handler import decode_access_token
from fastapi.security import OAuth2PasswordBearer
import pytz
import boto3
import os
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
import zipfile
from db import MongoDB
from auth.models import UserSchema, UserLoginSchema
from auth.hashing import hash_password, verify_password
from auth.jwt_handler import create_access_token, decode_access_token, create_access_token2
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pymongo

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

load_dotenv()

login_router = APIRouter()

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]
otp_collection = db["otps"]

def is_valid_object_id(id_str: str) -> bool:
    try:
        ObjectId(id_str)
        return True
    except Exception:
        return False

def serialize_mongo_document(document):

    if isinstance(document, list):
        return [serialize_mongo_document(doc) for doc in document]
    
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, dict) or isinstance(value, list):
                document[key] = serialize_mongo_document(value)
    return document

# def send_email(to_email: str, subject: str, body: str):
#     smtp_server = os.getenv("MAIL_SERVER")
#     smtp_port = os.getenv("MAIL_PORT")
#     smtp_username = os.getenv("MAIL_USERNAME")
#     smtp_password = os.getenv("MAIL_PASSWORD")
    
#     msg = MIMEMultipart()
#     msg["From"] = smtp_username
#     msg["To"] = to_email
#     msg["Subject"] = subject

#     msg.attach(MIMEText(body, "plain"))

#     with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
#         server.login(smtp_username, smtp_password)
#         server.sendmail(smtp_username, to_email, msg.as_string())

@login_router.post("/register")
async def register(user: UserSchema, request: Request):
    try:
        otp_record = await otp_collection.find_one({"email": user.email, "validated": True})
        if not otp_record:
            raise HTTPException(status_code=400, detail="Please complete OTP verification first.")

        # Check if the email already exists
        existing_email = await users_collection.find_one({"email": user.email})

        if existing_email:
            return {
                "status": "error",
                "message": "Email already registered. Please use a different email address.",
                "data": None,
                "error": "Email conflict.",
                "code": status.HTTP_400_BAD_REQUEST
            }
                   
        # Hash the password
        user.password = hash_password(user.password)

        generated_otp = ""

        # Convert user schema to dictionary and set default fields
        user_data = user.dict()
        user_data["role"] = "developer"  # Automatically set role as Developer
        user_data["status"] = "approved"  # Set initial status to pending

        await users_collection.insert_one(user_data)
        await otp_collection.delete_one({"email": user.email, "validated": True})

        return {
            "status": "success",
            "message": "User registered successfully.You can now login.",
            "data": {
                "user_id": str(user_data["_id"]),
                "status": user_data["status"]
            },
            "error": None,
            "code": status.HTTP_201_CREATED
        }
    
    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail,
            "data": None,
            "error": str(e),
            "code": e.status_code
        }
    except Exception as e:
        print(f"Error during registration: {e}")
        return {
            "status": "error",
            "message": "An error occurred during registration.",
            "data": None,
            "error": str(e),
            "code": status.HTTP_500_INTERNAL_SERVER_ERROR
        }
                                    
@login_router.post("/login")
async def login(user: UserLoginSchema):
    # Find the user by email
    if user.email:
        existing_user = await users_collection.find_one({"email": user.email})

    if not existing_user:
        return {
            "status": "error",
            "message": "The provided email is incorrect.",
            "data": None,
            "error": "Unauthorized access.",
            "code": status.HTTP_401_UNAUTHORIZED
        }

    # Check if the password is correct
    if not verify_password(user.password, existing_user["password"]):
        return {
            "status": "error",
            "message": "The provided password is incorrect.",
            "data": None,
            "error": "Unauthorized access.",
            "code": status.HTTP_401_UNAUTHORIZED
        }

    if existing_user["status"] != "approved":
        return {
            "status": "error",
            "message": "Account not approved by admin.",
            "data": None,
            "error": "Forbidden access.",
            "code": status.HTTP_403_FORBIDDEN
        }

    # Create the JWT token
    token = create_access_token({
        "user_id": str(existing_user["_id"]),
    })

    return {
        "status": "success",
        "message": "Login successful.",
        "data": {
            "access_token": token,
            "token_type": "bearer"
        },
        "error": None,
        "code": status.HTTP_200_OK
    }

@login_router.get("/user/profile")
async def get_user_profile(token: str = Depends(oauth2_scheme)):
    # Decode the access token to get user information
    user = decode_access_token(token)
    
    if "error" in user:
        return {
            "status": "error",
            "message": user["error"],
            "data": None,
            "error": "Unauthorized access.",
            "code": status.HTTP_401_UNAUTHORIZED
        }
    
    user_id = user.get("user_id")
    
    if not user_id:
        return {
            "status": "error",
            "message": "User ID not found in token.",
            "data": None,
            "error": "Invalid token.",
            "code": status.HTTP_400_BAD_REQUEST
        }

    user_info = await users_collection.find_one({"_id": ObjectId(user_id)})
    
    if not user_info:
        return {
            "status": "error",
            "message": "User not found.",
            "data": None,
            "error": "Not Found.",
            "code": status.HTTP_404_NOT_FOUND
        }

    # Prepare the user data to return in the response
    user_data = {
        "name": user_info.get("name"),
        "email": user_info.get("email")
    }
    
    return {
        "status": "success",
        "message": "User profile retrieved successfully.",
        "data": user_data,
        "error": None,
        "code": status.HTTP_200_OK
    }


#it will showcase all the pending users who requested for logging in
@login_router.get("/admin/pending_users", dependencies=[Depends(oauth2_scheme)])
async def get_pending_rejected_users(
    page: int = Query(1, description="Page number to fetch"),
    pagesize: int = Query(10, description="Number of records per page"),
):
    
    skip = (page - 1) * pagesize
    # Fetch users with 'pending' and 'rejected' status, and role as 'developer' from the database
    users_cursor = users_collection.find(
        {"status": {"$in": ["pending", "rejected"]}}
    ).sort("status", pymongo.ASCENDING).skip(skip).limit(pagesize)  # Sorting pending first
    
    users = await users_cursor.to_list(pagesize)

    total_count = await users_collection.count_documents(
        {"status": {"$in": ["pending", "rejected"]}}
    )
    
    if not users:
        return {
            "status": "success",
            "message": "No pending or rejected researcher users available.",
            "data": [],
            "error": None,
            "code": status.HTTP_200_OK
        }
    
    # Serialize the MongoDB documents for proper JSON response
    serialized_users = serialize_mongo_document(users)
    
    return {
        "status": "success",
        "message": "Pending and rejected researcher users fetched successfully.",
        "data": serialized_users,
        "totalcount": total_count,
        "page": page,
        "pagesize": pagesize,
        "error": None,
        "code": status.HTTP_200_OK
    }


@login_router.get("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    return {"msg": "Logged out successfully"}


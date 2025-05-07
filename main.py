import logging
import os
from datetime import datetime,time as dt_time,timedelta
from typing import List, Dict, Optional
import jwt
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status, Request, Header, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ValidationError
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pymongo import DESCENDING, MongoClient, ASCENDING
from auth.hashing import hash_password, verify_password
from auth.jwt_handler import create_access_token, decode_access_token, create_access_token2
from auth.models import UserSchema, UserLoginSchema
import pytz
from fastapi.exceptions import RequestValidationError
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import subprocess
import time
import sys
import pymongo
from db import MongoDB
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from auth.login import login_router as login_router
from chat.history import chat_router as chat_router
from chat.ask import ask_router as ask_router
from chat.vote import vote_router as vote_router
from chat.message import message_router as message_router
from auth.otp_routes import otp_router as otp_router

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Define the specific times for start and end dates
START_TIME = dt_time(0, 0, 0)  
END_TIME = dt_time(23, 59, 59)  

# Default constants
DEFAULT_REQUESTS_PER_MINUTE = 5
END_OF_DAY_TIME = dt_time(23, 59, 59)

def convert_utc_to_ist(utc_dt):
    # Ensure the input datetime is in UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=pytz.utc)
    return utc_dt.astimezone(IST)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(swagger_ui_parameters={"syntaxHighlight.theme": "obsidian"})

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(login_router)
app.include_router(chat_router)
app.include_router(ask_router)
app.include_router(otp_router)
app.include_router(vote_router)
app.include_router(message_router)

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Helper functions
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

def send_email(to_email: str, subject: str, body: str):
    smtp_server = os.getenv("MAIL_SERVER")
    smtp_port = os.getenv("MAIL_PORT")
    smtp_username = os.getenv("MAIL_USERNAME")
    smtp_password = os.getenv("MAIL_PASSWORD")
    
    msg = MIMEMultipart()
    msg["From"] = smtp_username
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_username, to_email, msg.as_string())

# Function to generate model-specific token
def generate_model_token(user_id: str, model_id: str, requests_per_minute: int, access_start_date: datetime, access_end_date: datetime, hashed_password: str = None):
    token_data = {
        "user_id": user_id,
        "model_id": model_id,
        "requests_per_minute": requests_per_minute,
        "access_start_date": access_start_date.isoformat(),
        "access_end_date": access_end_date.isoformat()
    }
    
    # If hashed_password is provided, include it in the token data
    if hashed_password:
        token_data["hashed_password"] = hashed_password
    
    # Generate JWT token specific to the model and pass access_end_date
    token = create_access_token2(token_data, access_end_date)
    return token


# Routes

@app.get("/")
async def check_working():
    return {"Transport Bot functioning properly"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Extract the error details from the exception
    error_messages = []
    for error in exc.errors():
        # Format each error message
        error_message = {
            "loc": error['loc'],
            "msg": "Mobile Number should only be in digits." if 'mobile_number' in error['loc'] else error['msg'],
            "type": error['type']
        }
        error_messages.append(error_message)
    
    # Return the custom error response in the required format
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "message": error_messages[0]['msg'],  # Show the first error message
            "data": None,
            "error": "Value Error",
            "code": HTTP_422_UNPROCESSABLE_ENTITY
        }
    )
    
# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

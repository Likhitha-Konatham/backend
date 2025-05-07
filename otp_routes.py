from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from random import randint
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import os
from db import MongoDB

otp_router = APIRouter()

# Initialize MongoDB client with motor
db = MongoDB.get_db()
users_collection = db["users"]
otp_collection = db["otps"]

class OTPRequest(BaseModel):
    email: str

@otp_router.post("/send-otp")
async def send_otp(data: OTPRequest):
    email = data.email

    # Check if email is already registered
    existing_user = await users_collection.find_one({"email": email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered. Please use a different email address.")

    # Generate OTP and set an expiration time (e.g., 5 minutes)
    generated_otp = str(randint(1000, 9999))
    expiration_time = datetime.utcnow() + timedelta(minutes=5)

    # Store OTP in the database with the email as the key
    await otp_collection.update_one(
        {"email": email},
        {"$set": {"otp": generated_otp, "expires_at": expiration_time}},
        upsert=True
    )

    # Send OTP via email
    sender_email = os.getenv("MAIL_USERNAME")  
    sender_password = os.getenv("MAIL_PASSWORD") 

    try:
        message = MIMEMultipart()
        message['From'] = sender_email
        message['To'] = email
        message['Subject'] = 'Your OTP Code'
        message.attach(MIMEText(f'Your OTP code is: {generated_otp}', 'plain'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())

        return {
            "status": "success",
            "message": "OTP sent successfully.",
            "data": None,
            "error": None,
            "code": status.HTTP_200_OK
        }
    except Exception as e:
        print(f'Error: {e}')
        raise HTTPException(status_code=500, detail="Failed to send OTP email.")

class ValidateOTPRequest(BaseModel):
    email: str
    enteredOTP: str

@otp_router.post("/validate-otp")
async def validate_otp(data: ValidateOTPRequest):
    email = data.email
    entered_otp = data.enteredOTP

    # Retrieve OTP from the database
    otp_record = await otp_collection.find_one({"email": email})

    if otp_record and otp_record["otp"] == entered_otp:
        # Check if OTP has expired
        if datetime.utcnow() > otp_record["expires_at"]:
            return {"isValid": False, "message": "OTP has expired."}
        
        # Mark OTP as validated
        await otp_collection.update_one(
            {"email": email},
            {"$set": {"validated": True}}
        )
        
        return {
            "status": "success",
            "message": "OTP validated successfully.",
            "isValid": True,
            "error": None,
            "code": status.HTTP_200_OK
        }

    else:
        return {"status":"error","isValid": False, "message": "Invalid OTP.", "code":status.HTTP_404_NOT_FOUND  }


class ForgotPasswordRequest(BaseModel):
    email: str

@otp_router.post("/forgot-password/send-otp")
async def forgot_password_send_otp(data: ForgotPasswordRequest):
    email = data.email

    # Check if the email exists in the database
    user = await users_collection.find_one({"email": email,"status":"approved"})
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered.")

    # Generate OTP and expiration time
    generated_otp = str(randint(1000, 9999))
    expiration_time = datetime.utcnow() + timedelta(minutes=5)

    # Store OTP in the database with purpose 'forgot-password'
    await otp_collection.update_one(
        {"email": email},
        {"$set": {"otp": generated_otp, "expires_at": expiration_time, "purpose": "forgot-password"}},
        upsert=True
    )

    # Send OTP via email
    try:
        message = MIMEMultipart()
        sender_email = os.getenv("MAIL_USERNAME")
        sender_password = os.getenv("MAIL_PASSWORD")
        message['From'] = sender_email
        message['To'] = email
        message['Subject'] = 'Password Reset OTP'
        message.attach(MIMEText(f'Your OTP for password reset is: {generated_otp}', 'plain'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())

        return {"status": "success", "message": "OTP sent for password reset.", "code": status.HTTP_200_OK}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to send OTP email.")

class ForgotPasswordValidateRequest(BaseModel):
    email: str
    entered_otp: str

@otp_router.post("/forgot-password/validate-otp")
async def forgot_password_validate_otp(data: ForgotPasswordValidateRequest):
    email = data.email
    entered_otp = data.entered_otp

    # Retrieve OTP from database
    otp_record = await otp_collection.find_one({"email": email, "purpose": "forgot-password"})
    if not otp_record:
        raise HTTPException(status_code=404, detail="OTP not found or invalid.")

    # Check if OTP matches and is not expired
    if otp_record["otp"] != entered_otp:
        return {"status": "error", "message": "Invalid OTP.", "code": status.HTTP_400_BAD_REQUEST}
    if datetime.utcnow() > otp_record["expires_at"]:
        return {"status": "error", "message": "OTP has expired.", "code": status.HTTP_400_BAD_REQUEST}

    # Mark OTP as validated
    await otp_collection.update_one(
        {"email": email, "purpose": "forgot-password"},
        {"$set": {"validated": True}}
    )
    return {"status": "success", "message": "OTP validated successfully.", "code": status.HTTP_200_OK}

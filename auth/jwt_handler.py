import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

# def create_access_token(data: dict) -> str:
#     payload = data.copy()
#     expiry = datetime.now() + timedelta(minutes=10)  # Token expires in 10 minutes
#     payload.update({"exp": expiry})
#     return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expiry = datetime.now() + timedelta(minutes=1440)  # Token expires in 24 hours
    payload.update({"exp": expiry})
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

def create_access_token2(data: dict, access_end_date: datetime) -> str:
    payload = data.copy()
    
    # Set the token expiration to the access_end_date
    payload.update({"exp": access_end_date})
    
    # Generate and return the JWT token
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

# def decode_access_token(token: str):
#     try:
#         payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
#         return payload
#     except jwt.ExpiredSignatureError:
#         return {"error": "Token has expired"}
#     except jwt.InvalidTokenError:
#         return {"error": "Invalid token"}

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        print(payload)
        return payload
    except jwt.ExpiredSignatureError:
        return {"error": "Token has expired"}
    except jwt.InvalidTokenError:
        return {"error": "Invalid token"}


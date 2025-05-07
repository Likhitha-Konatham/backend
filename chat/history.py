from datetime import datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from bson import ObjectId
from auth.jwt_handler import decode_access_token
from fastapi.security import OAuth2PasswordBearer
import pytz
from db import MongoDB

START_TIME = time(0, 0, 0)  # 12:00:00 AM
END_TIME = time(23, 59, 59)  # 11:59:59 PM

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Initialize router
chat_router = APIRouter()

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]
faq_collection = db["FAQs"]

@chat_router.get("/chat/history") 
async def get_chat_history(
    token: str = Depends(oauth2_scheme),
):
    # Decode the access token to get user information
    user = decode_access_token(token)
    
    if "error" in user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access."
        )
    
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID not found in token."
        )
    
    # Fetch conversations for the user
    conversations = await conversation_collection.find({"user_id": ObjectId(user_id)}).to_list(None)
    
    if not conversations:
        return {
            "status": "success",
            "message": "No chat history found.",
            "data": []
        }
    
    # Convert ObjectId to string for JSON serialization and add "title"
    def convert_objectid_fields(obj):
        """ Recursively converts ObjectId fields to strings in dictionaries and lists. """
        if isinstance(obj, dict):
            return {k: str(v) if isinstance(v, ObjectId) else convert_objectid_fields(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_objectid_fields(item) for item in obj]
        else:
            return obj

    conversations = [convert_objectid_fields(convo) for convo in conversations]

    # Set "title" as the first question in messages, if available
    for convo in conversations:
        convo["title"] = convo["messages"][0]["question"] if convo.get("messages") else "Untitled"

    return {
        "status": "success",
        "message": "Chat history retrieved successfully.",
        "data": conversations
    }



@chat_router.get("/chat/history/{conversation_id}")
async def get_specific_chat_history(conversation_id: str):
    try:
        conversation_obj_id = ObjectId(conversation_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation ID format."
        )

    conversation = await conversation_collection.find_one({"_id": conversation_obj_id})

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found."
        )

    def convert_objectid_fields(doc):
        if isinstance(doc, dict):
            return {k: str(v) if isinstance(v, ObjectId) else convert_objectid_fields(v) for k, v in doc.items()}
        elif isinstance(doc, list):
            return [convert_objectid_fields(i) for i in doc]
        else:
            return doc

    conversation = convert_objectid_fields(conversation)

    return {
        "status": "success",
        "message": "Chat history retrieved successfully.",
        "data": conversation
    }


@chat_router.get("/faqs/history/")
async def get_chat_history():
       
    # Fetch conversations for the user
    conversations = await faq_collection.find().to_list(None)
    
    if not conversations:
        return {
            "status": "success",
            "message": "No FAQs found.",
            "data": []
        }
    
    # Convert ObjectId to string for JSON serialization and add "title"
    for convo in conversations:
        convo["_id"] = str(convo["_id"])

    return {
        "status": "success",
        "message": "FAQs history retrieved successfully.",
        "data": conversations
    }

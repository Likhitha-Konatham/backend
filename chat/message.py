from fastapi import APIRouter, HTTPException, Path, Depends
from bson import ObjectId
from typing import Optional
from auth.jwt_handler import decode_access_token
from fastapi.security import OAuth2PasswordBearer
from db import MongoDB

# Initialize router
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)  # Note auto_error=False

async def get_optional_token(token: Optional[str] = Depends(oauth2_scheme)):
    return token

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]
models_collection = db["Models"]
forms_collection = db["Forms"]

message_router = APIRouter(prefix="/message")

@message_router.get("/summary/{message_id}")
async def get_summarized_response(
    message_id: str = Path(..., description="The message ID to fetch summary for"),
    token: Optional[str] = Depends(get_optional_token)
):
    # Authentication (optional)
    user_id = "guest"
    if token:
        user = decode_access_token(token)
        if "error" not in user:
            user_id = user.get("user_id", "guest")

    try:
        # Find the message in any conversation
        conversation = await conversation_collection.find_one(
            {"messages._id": ObjectId(message_id)},
            {"messages.$": 1, "user_id": 1}
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Message not found")

        # Check permissions (unless guest)
        if user_id != "guest" and str(conversation["user_id"]) != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Extract the message
        message = conversation["messages"][0]

        return {
            "status": "success",
            "message_id": str(message["_id"]),
            "summarized_response": message.get("summarized_response", ""),
            "tts_summary_url": message.get("tts_summary_url"),
            "tts_summary_status": message.get("tts_summary_status", "processing")
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
@message_router.get("/full/{message_id}")
async def get_full_response(
    message_id: str = Path(..., description="The message ID to fetch full response for"),
    token: Optional[str] = Depends(get_optional_token)
):
    # Authentication (same as above)
    user_id = "guest"
    if token:
        user = decode_access_token(token)
        if "error" not in user:
            user_id = user.get("user_id", "guest")

    try:
        # Find the message
        conversation = await conversation_collection.find_one(
            {"messages._id": ObjectId(message_id)},
            {"messages.$": 1, "user_id": 1}
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Message not found")

        # Check permissions
        if user_id != "guest" and str(conversation["user_id"]) != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        message = conversation["messages"][0]

        return {
            "status": "success",
            "message_id": str(message["_id"]),
            "full_response": message.get("response", ""),
            "tts_url": message.get("tts_url"),
            "tts_status": message.get("tts_status", "processing")
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid message ID")
    

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Path, BackgroundTasks
from bson import ObjectId
from auth.jwt_handler import decode_access_token
from fastapi.security import OAuth2PasswordBearer
import aiohttp
from db import MongoDB
from pydantic import BaseModel
from typing import Optional, Dict
import re
import time

# Initialize router
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)  # Note auto_error=False

async def get_optional_token(token: Optional[str] = Depends(oauth2_scheme)):
    return token

vote_router = APIRouter()

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]
models_collection = db["Models"]
forms_collection = db["Forms"]

@vote_router.post("/message/{message_id}/like")
async def like_message(
    message_id: str = Path(...),
    token: Optional[str] = Depends(get_optional_token)
):
    """API to like a message (vote = +1)"""
    return await _handle_vote(
        message_id=message_id,
        token=token,
        vote_type="liked",
        feedback=None
    )

@vote_router.post("/message/{message_id}/dislike")
async def dislike_message(
    feedback: str = Form(..., description="Required remarks for dislike"),
    message_id: str = Path(...),
    token: Optional[str] = Depends(get_optional_token)
):
    """API to dislike a message (vote = -1) with feedback"""
    return await _handle_vote(
        message_id=message_id,
        token=token,
        vote_type="disliked",
        feedback=feedback
    )

async def _handle_vote(
    message_id: str,
    token: Optional[str],
    vote_type: str,  # "liked" or "disliked"
    feedback: Optional[str]
):
    # Authentication
    if not token:
        raise HTTPException(status_code=401, detail="Login required to vote")
    
    user = decode_access_token(token)
    if "error" in user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Validate message ID
    try:
        message_obj_id = ObjectId(message_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid message ID format")
    
    # Find the conversation with this message
    conversation = await conversation_collection.find_one(
        {"messages._id": message_obj_id},
        {"messages.$": 1}
    )
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Message not found")
    
    message = conversation["messages"][0]
    current_vote = message.get("vote")
    
    # Prepare update operations
    update_ops = {
        "$set": {
            "messages.$.vote": vote_type,
        }
    }
    
    # Handle count changes
    if vote_type == "liked":
        if current_vote == "liked":
            raise HTTPException(status_code=400, detail="Already liked this message")
        
        update_ops["$inc"] = {"messages.$.like_count": 1}
        if current_vote == "disliked":
            update_ops["$inc"]["messages.$.dislike_count"] = -1
    
    else:  # disliked
        if current_vote == "disliked":
            raise HTTPException(status_code=400, detail="Already disliked this message")
        
        update_ops["$inc"] = {"messages.$.dislike_count": 1}
        update_ops["$set"]["messages.$.feedback"] = feedback
        if current_vote == "liked":
            update_ops["$inc"]["messages.$.like_count"] = -1
    
    # Apply updates
    result = await conversation_collection.update_one(
        {"messages._id": message_obj_id},
        update_ops
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update vote")
    
    return {"status": "success", "vote": vote_type}
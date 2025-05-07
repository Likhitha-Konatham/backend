from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Path, BackgroundTasks
from bson import ObjectId
from auth.jwt_handler import decode_access_token
from fastapi.security import OAuth2PasswordBearer
import aiohttp
from db import MongoDB
from pydantic import BaseModel
from typing import Optional
import re
import time
import os


CHATBOT_API_URL = os.getenv("CHATBOT_API_URL")

# Initialize router
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)  # Note auto_error=False

async def get_optional_token(token: Optional[str] = Depends(oauth2_scheme)):
    return token

ask_router = APIRouter()

db = MongoDB.get_db()
users_collection = db["users"]
conversation_collection = db["conversations"]
models_collection = db["Models"]
forms_collection = db["Forms"]

class ChatRequest(BaseModel):
    question: Optional[str] = None
    language: str = "English"

async def format_response_as_bullets(response_text: str, language: str) -> str:
    """
    ONLY replaces form names with links (e.g. "Form 1A" → "https://.../form1a.pdf")
    Returns the original text with just form links replaced
    """
    # Query all form names and their links from the database
    forms_data = await forms_collection.find().to_list(length=None)
    
    # Build a mapping of form identifiers to their links
    forms_dict = {}
    for form in forms_data:
        match = re.search(r"form[-\s]*(\d*[a-zA-Z]?\d*)", form["form_name"], re.IGNORECASE)
        if match and match.group(1):
            form_identifier = match.group(1).lower()
            forms_dict[form_identifier] = form["aws_link"]
    
    # Normalize "Form No" variations into standard format
    response_text = re.sub(
        r"form(?:[-\s]+(?:no\.?|number))?[-\s]*\n?\s*(\d*[a-zA-Z]?\d*)", 
        r"Form \1", 
        response_text, 
        flags=re.IGNORECASE
    )
    
    # Replace form identifiers with direct links
    for form_identifier, form_link in forms_dict.items():
        pattern = rf"(?<!\w)(?:Form(?:[-\s]+(?:No\.?|Number))?[-\s]*){re.escape(form_identifier)}(?!\w)"
        response_text = re.sub(
            pattern, 
            lambda match: f"{form_link}",  # Direct link replacement
            response_text, 
            flags=re.IGNORECASE
        )
    
    return response_text  # Return original text with ONLY form links replaced


async def get_translation(input_text: str, access_token: str, api_url: str):
    headers = {"access-token": f"{access_token}"}
    data = {"input_text": input_text}
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=data, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                print("NMT Result: ",result)
                return result.get("data", {}).get("output_text", "")
            else:
                raise HTTPException(status_code=500, detail="Translation API error")

def clean_text_for_tts(text):
    # Remove bullet points and unnecessary symbols
    cleaned_text = re.sub(r"•\s*", "", text)
    return cleaned_text.strip()

async def get_tts(text: str, access_token: str, api_url: str, gender: str = "male"):
    headers = {"access-token": access_token}
    data = {"text": text, "gender": gender}  # Defaulting to male

    # print("Data: ", data)
    # print("API URL: ", api_url)
    # print("Access-token: ", access_token)


    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=data, headers=headers) as response:
            response_text = await response.text()
            
            if response.status == 200:
                result = await response.json()
                return result.get("data", {}).get("s3_url", "")
            else:
                raise HTTPException(
                    status_code=response.status,
                    detail=f"TTS API error: {response.status} - {response_text}"
                )
            

async def get_asr(audio_file: UploadFile, access_token: str, api_url: str):
    headers = {"access-token": f"{access_token}"}  # No need to set Content-Type, aiohttp does it automatically
    
    form_data = aiohttp.FormData()  
    form_data.add_field("audio_file", await audio_file.read(), filename=audio_file.filename, content_type="audio/wav")

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, data=form_data) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("data", {}).get("recognized_text", "")
            else:
                error_text = await response.text()  # Get detailed error message
                raise HTTPException(status_code=500, detail=f"ASR API error: {error_text}")


async def get_or_create_conversation(user_id: str, language: str):
    user_id_obj = ObjectId(user_id) if user_id != "guest" else "guest"

    # Always create a new conversation
    new_conversation_id = ObjectId()
    new_conversation = {
        "_id": new_conversation_id,
        "user_id": user_id_obj,
        "conversation_id": new_conversation_id,
        "language": language,
        "messages": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    await conversation_collection.insert_one(new_conversation)
    
    return new_conversation_id

@ask_router.post("/ask/{conversation_id}")
async def store_chat_message(
    background_tasks: BackgroundTasks,
    conversation_id: str = Path(...),
    token: Optional[str] = Depends(get_optional_token),
    question: Optional[str] = Form(None),
    language: str = Form("English"),
    audio_file: Optional[UploadFile] = File(None)
):
    # Initialize timestamps dictionary
    timestamps = {
        "start_time": time.time(),
        "steps": {}
    }
    
    def log_timestamp(step_name):
        timestamps["steps"][step_name] = {
            "timestamp": time.time(),
            "elapsed": time.time() - timestamps["start_time"]
        }
    
    # Start logging
    log_timestamp("request_received")
    
    # Handle authentication - token is now optional
    user_id = "guest"  # Default to guest user
    if token:
        user = decode_access_token(token)
        if "error" not in user:
            user_id = user.get("user_id", "guest")
    
    if not question and not audio_file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either text or audio input is required")

    session_id = "null"  # Default session_id
    
    log_timestamp("authentication_complete")
    
    if conversation_id.lower() == "null":
        conversation_id = await get_or_create_conversation(user_id, language)
        log_timestamp("conversation_created")
    else:
        try:
            conversation_obj_id = ObjectId(conversation_id)
            existing_conversation = await conversation_collection.find_one({"_id": conversation_obj_id})
            if not existing_conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            
            # Check if the conversation belongs to the user (unless guest)
            if user_id != "guest" and str(existing_conversation.get("user_id")) != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to access this conversation")
                
            session_id = existing_conversation.get("session_id", "null")
            log_timestamp("existing_conversation_retrieved")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid conversation ID format")

    # Process ASR if audio file is provided
    if audio_file:
        asr_start = time.time()
        asr_model = await models_collection.find_one({"sourcelanguage": language, "model_type": "asr"})
        if not asr_model:
            raise HTTPException(status_code=500, detail="ASR model not found")
        question = await get_asr(audio_file, asr_model["access-token"], asr_model["api_url"])
        log_timestamp("asr_completed")
    
    original_question = question
    log_timestamp("question_processed")

    # Translate if needed (raw text only)
    if language.lower() != "english":
        translation_start = time.time()
        translation_model = await models_collection.find_one({"sourcelanguage": language, "targetlanguage": "English"})
        if not translation_model:
            raise HTTPException(status_code=500, detail="Translation model not found")
        translated_question = await get_translation(question, translation_model["access-token"], translation_model["api_url"])
        log_timestamp("translation_to_english_completed")
    else:
        translated_question = question

    # Call chatbot API with session_id
    chatbot_api_url = f"{CHATBOT_API_URL}/{session_id}"
    
    chatbot_start = time.time()
    async with aiohttp.ClientSession() as session:
        async with session.post(chatbot_api_url, json={"message": translated_question}) as response:
            if response.status == 200:
                chatbot_response = await response.json()
                raw_response_text = chatbot_response.get("response", "Chatbot did not return a response")
                summarized_response = chatbot_response.get("summarized_response", raw_response_text)  # Fallback to full response if no summary
                session_id = chatbot_response.get("session_id", session_id)
                log_timestamp("chatbot_response_received")
            else:
                raise HTTPException(status_code=500, detail="Chatbot API error")

    formatted_response = await format_response_as_bullets(raw_response_text, language)
    formatted_summary = await format_response_as_bullets(summarized_response, language)

    # Reverse translation if needed - PRIORITIZE SUMMARIZED RESPONSE FIRST
    if language.lower() != "english":
        reverse_translation_start = time.time()
        translation_model = await models_collection.find_one({"sourcelanguage": "English", "targetlanguage": language})
        if not translation_model:
            raise HTTPException(status_code=500, detail="Reverse translation model not found")
        
        # Translate summarized version first
        summarized_response = await get_translation(formatted_summary, translation_model["access-token"], translation_model["api_url"])
        
        # Then translate full response if different from summarized
        if summarized_response != raw_response_text:
            raw_response_text = await get_translation(formatted_response, translation_model["access-token"], translation_model["api_url"])
        
        log_timestamp("translation_to_original_completed")
    
    
    # Create message ID for tracking
    message_id = ObjectId()
    current_time = datetime.utcnow()
    
    # Updated message document with both responses
    initial_message = {
        "_id": message_id,
        "user_id": ObjectId(user_id) if user_id != "guest" else "guest",
        "question": original_question,
        "response": raw_response_text,
        "summarized_response": summarized_response,  # New field
        "formatted_response":formatted_response,
        "formatted_summary": formatted_summary,
        "raw_response": raw_response_text,
        "raw_summarized_response": summarized_response,  # New field
        "tts_url": None,
        "tts_summary_url": None,  # New field for summary TTS
        "timestamp": current_time,
        "tts_status": "processing",
        "tts_summary_status": "processing"  # New field
    }

    # Store the initial message in the conversation
    db_store_start = time.time()
    await conversation_collection.update_one(
        {"_id": ObjectId(conversation_id)},
        {"$push": {"messages": initial_message}},
        upsert=True
    )
    log_timestamp("database_store_completed")

    # Prepare updated response data
    response_data = {
        "status": "success",
        "message": "Chat stored successfully",
        "conversation_id": str(conversation_id),
        "session_id": session_id,
        "recognized_text": original_question,
        "message_id": str(message_id),
        "data": {
            "question": original_question,
            "response": raw_response_text,
            "summarized_response": summarized_response,  # New field
            "tts_output": None,
            "tts_summary_output": None,  # New field
            "tts_status": "processing",
            "tts_summary_status": "processing",  # New field
            "timestamp": current_time.isoformat()
        }
    }

    # Background task to process TTS and update the messages
    async def process_tts_and_update():
        try:
            tts_model = await models_collection.find_one({"sourcelanguage": language, "model_type": "tts"})
            if tts_model:
                # Process SUMMARY first
                clean_summary = clean_text_for_tts(summarized_response)
                tts_summary_url = await get_tts(clean_summary, tts_model["access-token"], tts_model["api_url"])
                
                # Then process FULL response if different
                if summarized_response != raw_response_text:
                    clean_text = clean_text_for_tts(raw_response_text)
                    tts_url = await get_tts(clean_text, tts_model["access-token"], tts_model["api_url"])
                else:
                    tts_url = tts_summary_url  # Use same audio if identical

                # Update message with both TTS URLs
                await conversation_collection.update_one(
                    {
                        "_id": ObjectId(conversation_id),
                        "messages._id": message_id
                    },
                    {
                        "$set": {
                            "messages.$.tts_url": tts_url,
                            "messages.$.tts_summary_url": tts_summary_url,
                            "messages.$.tts_status": "completed",
                            "messages.$.tts_summary_status": "completed",
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
        except Exception as e:
            print(f"Error in TTS background task: {str(e)}")
            # Update both statuses if TTS fails
            await conversation_collection.update_one(
                {
                    "_id": ObjectId(conversation_id),
                    "messages._id": message_id
                },
                {
                    "$set": {
                        "messages.$.tts_status": "failed",
                        "messages.$.tts_summary_status": "failed",
                        "updated_at": datetime.utcnow()
                    }
                }
            )

    background_tasks.add_task(process_tts_and_update)
    
    # Log pre-TTS timestamps
    log_timestamp("response_prepared")
    
    # Write initial timestamps to file (without TTS data)
    with open("performance_logs.txt", "a") as f:
        f.write(f"\n\n=== Request at {datetime.now().isoformat()} ===\n")
        for step, data in timestamps["steps"].items():
            f.write(f"{step}: {data['elapsed']:.3f}s\n")
        f.write(f"Pre-TTS total time: {time.time() - timestamps['start_time']:.3f}s\n")

    return response_data

@ask_router.delete("/conversation/{conversation_id}")
async def delete_conversation(
    conversation_id: str = Path(...),
    token: str = Depends(oauth2_scheme)
):
    user = decode_access_token(token)
    if "error" in user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized access")
    
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    
    try:
        conversation_obj_id = ObjectId(conversation_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid conversation ID format")
    
    conversation = await conversation_collection.find_one({"_id": conversation_obj_id, "user_id": ObjectId(user_id)})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    await conversation_collection.delete_one({"_id": conversation_obj_id})
    
    return {
        "status": "success",
        "data": None,
        "error": None,
        "message": "Conversation deleted successfully",
        "code":200
    }

@ask_router.get("/message/{message_id}")
async def get_message_status(
    message_id: str = Path(...),
    token: Optional[str] = Depends(get_optional_token)  # Using our custom optional token dependency
):
    # Authentication - handle both authenticated and guest users
    user_id = "guest"  # Default to guest user
    if token:
        user = decode_access_token(token)
        if "error" not in user:
            user_id = user.get("user_id")
    
    # Validate message ID format
    try:
        message_obj_id = ObjectId(message_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid message ID format")
    
    # Build query based on user type
    query = {
        "messages._id": message_obj_id
    }
    
    # For authenticated users, add user_id check
    if user_id != "guest":
        query["user_id"] = ObjectId(user_id)
    # For guest users, we only check the message_id
    
    # Find any conversation containing this message
    conversation = await conversation_collection.find_one(
        query,
        {"messages.$": 1}  # Only return the matching message
    )
    
    if not conversation or not conversation.get("messages"):
        raise HTTPException(
            status_code=404,
            detail="Message not found or you don't have permission to access it"
        )
    
    message = conversation["messages"][0]
    
    return {
        "status": "success",
        "data": {
            "tts_status": message.get("tts_status", "unknown"),
            "tts_url": message.get("tts_url", None),
            "tts_summary_status": message.get("tts_summary_status", "unknown"),
            "tts_summary_url": message.get("tts_summary_url", None),
            "last_updated": message.get("timestamp"),
            "like_count": message.get("like_count", 0),
            "dislike_count": message.get("dislike_count", 0),
            "feedback": message.get("feedback"),
            "vote": message.get("vote") 
        }
    }

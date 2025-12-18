# app/api/endpoints/whatsapp.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse  # <--- IMPORT THIS
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.schemas import WhatsAppWebhookSchema
from app.services.chat_manager import process_message

router = APIRouter()
VERIFY_TOKEN = "blue_chameleon_2025" 


@router.get("/webhook")
async def verify_webhook(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge")
):
    # Check if mode is 'subscribe' and token matches
    if mode == "subscribe" and token == VERIFY_TOKEN:
        # CRITICAL FIX: Return PlainTextResponse, not int()
        return PlainTextResponse(content=challenge, status_code=200)
    
    raise HTTPException(status_code=403, detail="Invalid Token")

# --- 2. EVENT NOTIFICATION ENDPOINT (POST) ---
@router.post("/webhook")
async def whatsapp_webhook(payload: WhatsAppWebhookSchema, db: Session = Depends(get_db)):
    data = payload.model_dump(by_alias=True)
    try:
        # Safety Check: Ensure 'entry' exists
        if not data.get('entry'):
            return {"status": "ignored"}

        entry = data['entry'][0]
        changes = entry.get('changes', [])
        
        if not changes:
            return {"status": "ignored"}
            
        value = changes[0].get('value', {})
        
        # Check if this is a MESSAGE (not a status update like 'read' or 'delivered')
        if 'messages' in value and value['messages']:
            msg = value['messages'][0]
            
            # Extract User Info safely
            user_id = msg['from']
            user_name = "Student"
            contacts = value.get('contacts', [])
            if contacts:
                user_name = contacts[0].get('profile', {}).get('name', "Student")
            
            # Extract Message Body (Handle Text Only for now)
            text_body = ""
            if msg['type'] == 'text':
                text_body = msg['text']['body']
            else:
                text_body = "[Media/Image Received]" # Placeholder for non-text
            
            # Send to The Brain 🧠
            process_message(
                platform="whatsapp",
                user_id=user_id,
                user_name=user_name,
                message_text=text_body,
                db=db
            )
            
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        
    # Always return 200 OK to Meta, otherwise they will keep retrying
    return {"status": "received"}
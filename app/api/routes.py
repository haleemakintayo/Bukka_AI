# app/api/routes.py
import os
import requests
import json
import time  # <--- NEW: Added time import
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session

# Database Imports
from app.core.database import get_db
from app.models.sql_models import User, Order
from app.models.schemas import WhatsAppMessage, ConsultantResponse, WhatsAppWebhookSchema

# AI Imports
from app.services.llm_engine import order_chain, consultant_agent
from app.core.config import settings

router = APIRouter()

# --- 1. CONFIGURATION ---
VERIFY_TOKEN = "blue_chameleon_2025"
META_TOKEN = os.getenv("META_API_TOKEN") 
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") 
OWNER_PHONE = "2348012345678"  # Ensure this matches your frontend OWNER phone

# --- 2. DEMO MEMORY ---
DEMO_CHATS = []

@router.get("/demo/chats")
async def get_demo_chats():
    return DEMO_CHATS

@router.post("/demo/reset")
async def reset_demo_chats():
    global DEMO_CHATS
    DEMO_CHATS = []
    return {"status": "cleared"}

# --- 3. HELPER FUNCTIONS ---

def send_whatsapp_message(to_number: str, message_text: str):
    """Sends via Meta AND saves for the Demo Frontend."""
    print(f"📤 SENDING REPLY TO {to_number}: {message_text}")
    
    # 1. Save to Memory with REAL TIMESTAMP
    # FIX: Use time.time() so it sorts correctly in the frontend
    current_timestamp = int(time.time()) 
    
    DEMO_CHATS.append({
        "id": f"msg_{len(DEMO_CHATS)+1}",
        "direction": "outbound",
        "from": "BukkaAI",
        "to": to_number,
        "body": message_text,
        "timestamp": current_timestamp # <--- FIXED TIMESTAMP
    })
    
    # 2. Try sending via Real Meta API
    try:
        url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {META_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message_text}
        }
        requests.post(url, json=payload, headers=headers)
    except Exception as e:
        print(f"Meta Send Failed (Expected in Demo): {e}")

def handle_owner_confirmation(db: Session, message_text: str):
    """Helper to process the owner's 'CONFIRM EMEKA' command."""
    try:
        parts = message_text.split()
        if len(parts) < 2: return "Format error. Use: CONFIRM <NAME>"
        student_name = parts[1] 
        
        user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
        if user:
            order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                send_whatsapp_message(user.phone_number, "✅ Payment Confirmed! Your food is being packed.")
                return f"Approved {student_name}'s order."
            else:
                return f"{student_name} has no pending orders."
        return "Student not found."
    except Exception as e:
        print(f"Owner Logic Error: {e}")
        return "Error processing confirmation."

# --- 4. API ROUTES ---

@router.get("/webhook")
async def verify_webhook(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge")
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid Token")

@router.post("/webhook")
async def whatsapp_webhook(
    payload: WhatsAppWebhookSchema, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    data = payload.model_dump(by_alias=True)
    
    try:
        entry = data['entry'][0]['changes'][0]['value']
        
        if 'messages' not in entry or not entry['messages']:
            return {"status": "ignored"}
            
        message = entry['messages'][0]
        user_phone = message['from']
        message_text = message['text']['body']
        
        print(f"📥 RECEIVED MESSAGE from {user_phone}: {message_text}")

        # FIX: Ensure incoming messages also have valid timestamps
        incoming_timestamp = int(message.get('timestamp', time.time()))

        DEMO_CHATS.append({
             "id": message.get('id', f'temp_{time.time()}'),
             "direction": "inbound",
             "from": user_phone,
             "to": "BukkaAI",
             "body": message_text,
             "timestamp": incoming_timestamp
        })
        
        # --- A. OWNER LOGIC ---
        if user_phone == OWNER_PHONE and "CONFIRM" in message_text.upper():
            reply = handle_owner_confirmation(db, message_text)
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, reply)
            return {"status": "owner_action_processed"}

        # --- B. STUDENT LOGIC ---
        user_name = "Student"
        if entry.get('contacts'):
            user_name = entry['contacts'][0]['profile']['name']
            
        user = db.query(User).filter(User.phone_number == user_phone).first()
        if not user:
            user = User(phone_number=user_phone, name=user_name)
            db.add(user)
            db.commit()

        if "PAID" in message_text.upper():
            alert_msg = f"💰 PAYMENT ALERT: {user_name} says they paid.\nReply 'CONFIRM {user_name}' to approve."
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, alert_msg)
            background_tasks.add_task(send_whatsapp_message, user_phone, "Okay! Asking Auntie to confirm...")
            return {"status": "payment_reported"}

        # ... inside whatsapp_webhook function ...

        # 3. AI Order Logic (DEBUG MODE)
        try:
            print(f"🤖 ASKING AI: {message_text}")
            
            response_data = order_chain.invoke({
                "menu": str(settings.MENU),
                "user_input": message_text
            })
            
            # --- DEBUGGING: Print exact output to logs ---
            print(f"🧠 AI RAW OUTPUT: {response_data}")
            
            # Smart Parsing Strategy
            ai_reply = None
            
            # Case 1: It's a Dictionary (Correct JSON)
            if isinstance(response_data, dict):
                ai_reply = response_data.get('reply_message') or \
                           response_data.get('text') or \
                           response_data.get('response') or \
                           response_data.get('output')
                intent = response_data.get('intent', 'UNKNOWN')
            
            # Case 2: It's just a String (Raw text)
            elif isinstance(response_data, str):
                ai_reply = response_data
                intent = "UNKNOWN"

            # Case 3: Still None? Force a Dump so we can see it in the Frontend
            if not ai_reply:
                ai_reply = f"[DEBUG] AI Format Error. Raw Data: {str(response_data)}"

        except Exception as ai_error:
            print(f"❌ AI CRASH: {ai_error}")
            # Send the actual crash error to the frontend so you can see it
            ai_reply = f"[DEBUG] System Error: {str(ai_error)}"
            intent = "ERROR"
        
        # Send the final reply (or the Debug Error)
        if intent == "ORDER":
            final_reply = ai_reply + "\n\nPay to Opay: 123456. Reply 'PAID' when done."
            background_tasks.add_task(send_whatsapp_message, user_phone, final_reply)
        else:
            background_tasks.add_task(send_whatsapp_message, user_phone, ai_reply)

    except KeyError as e:
        print(f"⚠️ MISSING DATA KEY: {e}") 
    except Exception as e:
        print(f"❌ GENERAL ERROR: {e}")
        
    return {"status": "received"}

# --- 5. CONSULTANT ENDPOINT ---
@router.post("/consult", response_model=ConsultantResponse)
async def consult_endpoint(payload: WhatsAppMessage):
    return {"advice": "Consultant active", "source": "System"}
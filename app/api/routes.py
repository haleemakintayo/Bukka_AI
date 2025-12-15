# app/api/routes.py
import os
import requests
import json
import time 
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
OWNER_PHONE = "2348012345678" 

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
def get_formatted_history(user_phone: str, limit: int = 10) -> str:
    user_chats = [
        c for c in DEMO_CHATS 
        if c.get("from") == user_phone or c.get("to") == user_phone
    ]
    recent_history = user_chats[-(limit+1):-1]
    
    context_str = ""
    for msg in recent_history:
        sender = "User" if msg["from"] == user_phone else "AI"
        context_str += f"{sender}: {msg['body']}\n"
        
    return context_str

def send_whatsapp_message(to_number: str, message_text: str):
    """Sends via Meta AND saves for the Demo Frontend (SYNCHRONOUS)."""
    print(f"📤 SENDING REPLY TO {to_number}: {message_text}")
    
    # 1. Save to Memory with REAL TIMESTAMP
    current_timestamp = int(time.time()) 
    
    DEMO_CHATS.append({
        "id": f"msg_{len(DEMO_CHATS)+1}",
        "direction": "outbound",
        "from": "BukkaAI",
        "to": to_number,
        "body": message_text,
        "timestamp": current_timestamp
    })
    
    # 2. Try sending via Real Meta API (Fire and forget, but wait for error)
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
        # Timeout ensures we don't hang if Meta is slow
        requests.post(url, json=payload, headers=headers, timeout=1.0)
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

        # Store Incoming
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
            send_whatsapp_message(OWNER_PHONE, reply) # Sync
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

        # --- C. PAYMENT REPORT LOGIC (Debugged) ---
        if "PAID" in message_text.upper() or "IVE PAID" in message_text.upper():
            print(f"💰 Processing PAID trigger for {user_name}...")
            try:
                existing_order = db.query(Order).filter(
                    Order.user_id == user.id, 
                    Order.status == "Pending"
                ).first()
                
                if not existing_order:
                    print(f"📝 Creating Missing Order for {user_name}")
                    new_order = Order(
                        user_id=user.id,
                        items="Assorted Food (AI Chat)", 
                        total_price=0.0,
                        status="Pending"
                    )
                    db.add(new_order)
                    db.commit()
                
                # Notify Immediately (SYNC)
                send_whatsapp_message(OWNER_PHONE, f"💰 PAYMENT ALERT: {user_name} says they paid.\nReply 'CONFIRM {user_name}' to approve.")
                send_whatsapp_message(user_phone, "Okay! Asking Auntie to confirm...")
                
                return {"status": "payment_reported"}
            except Exception as e:
                print(f"❌ PAID LOGIC ERROR: {e}")
                send_whatsapp_message(user_phone, "Error processing payment. Please wait.")
                return {"status": "error"}

        # --- D. AI ORDER LOGIC ---
        try:
            history_context = get_formatted_history(user_phone)
            
            full_prompt_input = (
                f"HISTORY OF CONVERSATION:\n{history_context}\n"
                f"CURRENT USER MESSAGE: {message_text}"
            )
            
            print(f"🧠 SENDING TO AI: {full_prompt_input}")

            response_data = order_chain.invoke({
                "menu": str(settings.MENU),
                "user_input": full_prompt_input
            })
            
            print(f"🧠 AI RAW OUTPUT: {response_data}") 
            
            ai_reply = None
            intent = "CHITCHAT" 
            
            if isinstance(response_data, dict):
                # 1. Extract Message
                ai_reply = response_data.get('message') or \
                           response_data.get('reply_message') or \
                           response_data.get('text')
                
                if not ai_reply:
                    for value in response_data.values():
                        if isinstance(value, str):
                            ai_reply = value
                            break

                # 2. Check Status for Payment Prompt
                if response_data.get('status') == 'complete':
                    intent = "ORDER"
                else:
                    intent = "CHITCHAT"

            elif isinstance(response_data, str):
                ai_reply = response_data

            if not ai_reply:
                ai_reply = "I didn't quite understand. Could you rephrase?"

        except Exception as ai_error:
            print(f"AI Generation Error: {ai_error}")
            intent = "CHITCHAT"
            ai_reply = "Sorry, network is bad. Say that again?"
        
        # --- SEND REPLY (SYNC) ---
        if intent == "ORDER":
            final_reply = f"{ai_reply}\n\nPay to Opay: 123456. Reply 'PAID' when done."
            send_whatsapp_message(user_phone, final_reply)
        else:
            send_whatsapp_message(user_phone, ai_reply)

    except KeyError as e:
        print(f"⚠️ MISSING DATA KEY: {e}") 
    except Exception as e:
        print(f"❌ GENERAL ERROR: {e}")
        
    return {"status": "received"}

# --- 5. CONSULTANT ENDPOINT ---
@router.post("/consult", response_model=ConsultantResponse)
async def consult_endpoint(payload: WhatsAppMessage):
    return {"advice": "Consultant active", "source": "System"}
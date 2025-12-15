# app/api/routes.py
import os
import requests
import json
import time 
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

# Database Imports
from app.core.database import get_db
from app.models.sql_models import User, Order
from app.models.schemas import WhatsAppMessage, ConsultantResponse, WhatsAppWebhookSchema

# AI Imports
from app.services.llm_engine import order_chain
from app.core.config import settings

router = APIRouter()

# --- CONFIGURATION ---
VERIFY_TOKEN = "blue_chameleon_2025"
META_TOKEN = os.getenv("META_API_TOKEN") 
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") 
OWNER_PHONE = "2348012345678" 

# --- MEMORY ---
DEMO_CHATS = []

@router.get("/demo/chats")
async def get_demo_chats():
    return DEMO_CHATS

@router.post("/demo/reset")
async def reset_demo_chats():
    global DEMO_CHATS
    DEMO_CHATS = []
    return {"status": "cleared"}

# --- HELPER FUNCTIONS ---
def get_current_time_ms():
    """Returns current timestamp in MILLISECONDS (Senior Eng Fix for Sorting)"""
    return int(time.time() * 1000)

def get_formatted_history(user_phone: str, limit: int = 10) -> str:
    user_chats = [c for c in DEMO_CHATS if c.get("from") == user_phone or c.get("to") == user_phone]
    recent_history = user_chats[-(limit+1):-1]
    
    context_str = ""
    for msg in recent_history:
        sender = "User" if msg["from"] == user_phone else "AI"
        context_str += f"{sender}: {msg['body']}\n"
    return context_str

def send_whatsapp_message(to_number: str, message_text: str):
    """Sends via Meta AND saves for Frontend (Synchronous for safety)."""
    print(f"📤 SENDING REPLY TO {to_number}: {message_text}")
    
    # SAVE TO MEMORY (Milliseconds)
    DEMO_CHATS.append({
        "id": f"msg_{len(DEMO_CHATS)+1}",
        "direction": "outbound",
        "from": "BukkaAI",
        "to": to_number,
        "body": message_text,
        "timestamp": get_current_time_ms()
    })
    
    # SEND TO META
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
        requests.post(url, json=payload, headers=headers, timeout=1.0)
    except Exception as e:
        print(f"Meta Send Failed: {e}")

def handle_owner_confirmation(db: Session, message_text: str):
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

# --- MAIN WEBHOOK ---
@router.post("/webhook")
async def whatsapp_webhook(
    payload: WhatsAppWebhookSchema, 
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
        
        print(f"📥 RECEIVED from {user_phone}: {message_text}")

        # Store Incoming (Milliseconds)
        DEMO_CHATS.append({
             "id": message.get('id', f'temp_{time.time()}'),
             "direction": "inbound",
             "from": user_phone,
             "to": "BukkaAI",
             "body": message_text,
             "timestamp": get_current_time_ms()
        })
        
        # --- 1. OWNER LOGIC ---
        if user_phone == OWNER_PHONE and "CONFIRM" in message_text.upper():
            reply = handle_owner_confirmation(db, message_text)
            send_whatsapp_message(OWNER_PHONE, reply)
            return {"status": "owner_action_processed"}

        # --- 2. STUDENT USER MANAGEMENT ---
        user_name = "Student"
        if entry.get('contacts'):
            user_name = entry['contacts'][0]['profile']['name']
            
        user = db.query(User).filter(User.phone_number == user_phone).first()
        if not user:
            user = User(phone_number=user_phone, name=user_name)
            db.add(user)
            db.commit()
            db.refresh(user) # <--- CRITICAL FIX: Ensure ID exists

        # --- 3. PAYMENT FLOW (STATE MACHINE) ---
        
        # TRIGGER: User says "PAID"
        if "PAID" in message_text.upper() and len(message_text) < 20:
            send_whatsapp_message(user_phone, "Okay! Abeg, wetin be the NAME on the account you use send money?")
            return {"status": "asked_for_name"}

        # TRIGGER: User replies with Name (Heuristic: Short text & Pending Order exists)
        # We check if there is a pending order that needs verification
        pending_order = db.query(Order).filter(
            Order.user_id == user.id, 
            Order.status == "Pending"
        ).first()

        # If they have a pending order but the last message from AI was asking for a name...
        # For simplicity in this hackathon, if they send a short text that IS NOT "PAID", and have a pending order, we assume it's the name.
        if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
             payment_name = message_text
             
             # Notify Owner
             alert = f"💰 PAYMENT ALERT!\nStudent: {user_name}\nAcct Name: {payment_name}\nReply 'CONFIRM {user_name}' to approve."
             send_whatsapp_message(OWNER_PHONE, alert)
             
             # Notify Student
             send_whatsapp_message(user_phone, "Seen! I don tell Auntie. Make you wait small for confirmation.")
             return {"status": "alert_sent"}

        # --- 4. AI ORDER LOGIC ---
        try:
            history = get_formatted_history(user_phone)
            full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"
            
            print(f"🧠 AI THINKING...")
            response_data = order_chain.invoke({
                "menu": str(settings.MENU),
                "user_input": full_prompt
            })
            print(f"🧠 AI OUTPUT: {response_data}") 
            
            ai_reply = None
            intent = "CHITCHAT" 
            
            if isinstance(response_data, dict):
                ai_reply = response_data.get('message') or response_data.get('reply_message') or response_data.get('text')
                
                # Fallback search
                if not ai_reply:
                    for v in response_data.values():
                        if isinstance(v, str): ai_reply = v; break

                if response_data.get('status') == 'complete':
                    intent = "ORDER"

            elif isinstance(response_data, str):
                ai_reply = response_data

            if not ai_reply: ai_reply = "I didn't quite understand."

        except Exception as ai_error:
            print(f"AI Error: {ai_error}")
            ai_reply = "Sorry, network don do anyhow."
        
        # --- 5. SEND FINAL REPLY ---
        if intent == "ORDER":
            # Creating the Pending Order NOW so the Payment Flow works later
            if not pending_order:
                print(f"📝 Creating Order for {user_name}")
                new_order = Order(
                    user_id=user.id,
                    items="Assorted (AI)", 
                    total_price=0.0,
                    status="Pending"
                )
                db.add(new_order)
                db.commit()

            final_reply = f"{ai_reply}\n\nPay to Opay: 123456.\nReply 'PAID' when done."
            send_whatsapp_message(user_phone, final_reply)
        else:
            send_whatsapp_message(user_phone, ai_reply)

    except Exception as e:
        print(f"❌ GENERAL ERROR: {e}")
        
    return {"status": "received"}

@router.get("/webhook")
async def verify_webhook(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")):
    if mode == "subscribe" and token == VERIFY_TOKEN: return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid Token")
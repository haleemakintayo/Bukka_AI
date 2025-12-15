# app/api/routes.py
import os
import requests
import json
import time 
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# REPLACE THIS WITH YOUR REAL WHATSAPP NUMBER
OWNER_PHONE = "2349068778689" 

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
    """Returns timestamp in Milliseconds to fix sorting issues."""
    return int(time.time() * 1000)

def get_formatted_history(user_identifier: str, limit: int = 10) -> str:
    # Handles both Phone Numbers and Chat IDs
    user_chats = [c for c in DEMO_CHATS if str(c.get("from")) == str(user_identifier) or str(c.get("to")) == str(user_identifier)]
    recent_history = user_chats[-(limit+1):-1]
    
    context_str = ""
    for msg in recent_history:
        sender = "User" if str(msg["from"]) == str(user_identifier) else "AI"
        context_str += f"{sender}: {msg['body']}\n"
    return context_str

# --- UNIFIED SENDING ENGINE (WhatsApp + Telegram) ---
def send_reply(platform: str, to_id: str, message_text: str):
    """
    Sends message to the correct platform AND saves to Demo Frontend.
    """
    print(f"📤 SENDING ({platform}) TO {to_id}: {message_text}")
    
    # 1. SAVE TO MEMORY (Milliseconds)
    DEMO_CHATS.append({
        "id": f"msg_{len(DEMO_CHATS)+1}",
        "direction": "outbound",
        "from": "BukkaAI",
        "to": to_id,
        "body": message_text,
        "timestamp": get_current_time_ms(),
        "platform": platform
    })
    
    # 2. SEND VIA API
    try:
        if platform == "whatsapp":
            url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
            headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": to_id, "type": "text", "text": {"body": message_text}}
            requests.post(url, json=payload, headers=headers, timeout=2.0)
            
        elif platform == "telegram":
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": to_id, "text": message_text}
            requests.post(url, json=payload, timeout=2.0)
            
    except Exception as e:
        print(f"⚠️ {platform} Send Failed: {e}")

# --- THE LOGIC BRAIN 🧠 ---
def process_message(platform: str, user_id: str, user_name: str, message_text: str, db: Session):
    """
    Unified Logic for ALL Platforms.
    """
    # 1. Store Incoming
    DEMO_CHATS.append({
         "id": f"in_{time.time()}",
         "direction": "inbound",
         "from": str(user_id),
         "to": "BukkaAI",
         "body": message_text,
         "timestamp": get_current_time_ms(),
         "platform": platform
    })
    
    # 2. User Management (Safe Create)
    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 3. Payment Flow (The "Verification" Logic)
    
    # TRIGGER A: User says "PAID" -> Ask for Name
    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Abeg, wetin be the NAME on the account you use send money?")
        return

    # TRIGGER B: User sends Name -> Alert Owner
    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    
    # If pending order exists AND message is short AND NOT "CONFIRM" -> Assume it's the Name
    if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
         payment_name = message_text
         
         # Notify Owner (Always on WhatsApp)
         alert = f"💰 {platform.upper()} ALERT!\nUser: {user_name}\nAcct Name: {payment_name}\nReply 'CONFIRM {user_name}' to approve."
         send_reply("whatsapp", OWNER_PHONE, alert)
         
         # Notify Student
         send_reply(platform, user_id, "Seen! I don tell Auntie. Make you wait small for confirmation.")
         return

    # 4. AI Logic
    try:
        history = get_formatted_history(user_id)
        full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"
        
        response_data = order_chain.invoke({"menu": str(settings.MENU), "user_input": full_prompt})
        
        ai_reply = None
        intent = "CHITCHAT" 
        
        # Robust Parsing
        if isinstance(response_data, dict):
            ai_reply = response_data.get('message') or response_data.get('text')
            if not ai_reply:
                for v in response_data.values():
                    if isinstance(v, str): ai_reply = v; break
            if response_data.get('status') == 'complete':
                intent = "ORDER"
        elif isinstance(response_data, str):
            ai_reply = response_data

        if not ai_reply: ai_reply = "I didn't quite understand."
        
        # 5. Send Final Reply
        if intent == "ORDER":
            # Safety: Create Order if missing
            if not pending_order:
                print(f"📝 Creating New Order for {user_name}")
                new_order = Order(user_id=user.id, items="Assorted (AI)", total_price=0.0, status="Pending")
                db.add(new_order)
                db.commit()
            
            final_reply = f"{ai_reply}\n\nPay to Opay: 123456.\nReply 'PAID' when done."
            send_reply(platform, user_id, final_reply)
        else:
            send_reply(platform, user_id, ai_reply)

    except Exception as e:
        print(f"❌ LOGIC ERROR: {e}")
        send_reply(platform, user_id, "Sorry, network don do anyhow. Try again.")


# --- TELEGRAM WEBHOOK ---
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "message" in data:
            msg = data["message"]
            chat_id = str(msg["chat"]["id"])
            user_name = msg["from"].get("first_name", "Telegram User")
            text = msg.get("text", "")
            
            print(f"📥 TELEGRAM: {text}")
            process_message("telegram", chat_id, user_name, text, db)
            
        return {"status": "ok"}
    except Exception as e:
        print(f"Telegram Error: {e}")
        return {"status": "error"}


# --- WHATSAPP WEBHOOK ---
@router.post("/webhook")
async def whatsapp_webhook(payload: WhatsAppWebhookSchema, db: Session = Depends(get_db)):
    data = payload.model_dump(by_alias=True)
    try:
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' not in entry or not entry['messages']: return {"status": "ignored"}
            
        message = entry['messages'][0]
        user_phone = message['from']
        message_text = message['text']['body']
        
        # OWNER COMMAND OVERRIDE
        if user_phone == OWNER_PHONE and "CONFIRM" in message_text.upper():
            parts = message_text.split()
            if len(parts) >= 2:
                student_name = parts[1]
                target_user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
                if target_user:
                    order = db.query(Order).filter(Order.user_id == target_user.id, Order.status == "Pending").first()
                    if order:
                        order.status = "PAID"
                        db.commit()
                        send_reply("whatsapp", OWNER_PHONE, f"Approved {student_name}'s order.")
                        # Alert the user on their platform (detect via phone number format)
                        platform = "whatsapp" # Default
                        # If user ID is short (Telegram) vs Long (WhatsApp), we could guess, but send_reply handles logic
                        # Actually, we need to know the platform. For now, assume WhatsApp if phone number matches.
                        # For Telegram users, we might need to store platform in User DB. 
                        # HACK: Try sending to WhatsApp first.
                        send_reply("whatsapp", target_user.phone_number, "✅ Payment Confirmed! Your food is being packed.")
                        # If it was telegram, the whatsapp send fails, we can add retry logic later.
                    else:
                        send_reply("whatsapp", OWNER_PHONE, "No pending order found.")
                else:
                    send_reply("whatsapp", OWNER_PHONE, "Student not found.")
            return {"status": "owner_processed"}

        # STANDARD USER
        user_name = "Student"
        if entry.get('contacts'): user_name = entry['contacts'][0]['profile']['name']
        
        process_message("whatsapp", user_phone, user_name, message_text, db)
        
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        
    return {"status": "received"}

@router.get("/webhook")
async def verify_webhook(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")):
    if mode == "subscribe" and token == VERIFY_TOKEN: return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid Token")
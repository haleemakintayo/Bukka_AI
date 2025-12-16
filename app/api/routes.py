# app/api/routes.py
import os
import requests
import json
import time 
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Database Imports
from app.core.database import get_db
from app.models.sql_models import User, Order, Message
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

# --- OWNER SETTINGS ---
# Set this to "telegram" or "whatsapp"
OWNER_PLATFORM = "telegram" 

# Put your Telegram Chat ID here (since you are testing on Telegram)
# To get your ID, chat with @userinfobot on Telegram
OWNER_ID = "7490888563" 

# --- HELPER: TIME ---
def get_current_time_ms():
    return int(time.time() * 1000)

# --- ENDPOINT: FRONTEND POLLING ---
@router.get("/demo/chats")
async def get_demo_chats(db: Session = Depends(get_db)):
    msgs = db.query(Message).order_by(Message.timestamp.desc()).limit(50).all()
    return [
        {
            "id": str(m.id),
            "direction": m.direction,
            "from": m.contact_id if m.direction == "inbound" else "BukkaAI",
            "to": "BukkaAI" if m.direction == "inbound" else m.contact_id,
            "body": m.body,
            "timestamp": m.timestamp,
            "platform": m.platform
        }
        for m in reversed(msgs)
    ]

@router.post("/demo/reset")
async def reset_demo_chats(db: Session = Depends(get_db)):
    db.query(Message).delete()
    db.commit()
    return {"status": "cleared"}

# --- HELPER: SAVE & SEND ---
def send_reply(platform: str, to_id: str, message_text: str, db: Session):
    print(f"📤 SENDING ({platform}) TO {to_id}: {message_text}")
    
    new_msg = Message(
        platform=platform,
        contact_id=str(to_id),
        direction="outbound",
        body=message_text,
        timestamp=get_current_time_ms()
    )
    db.add(new_msg)
    db.commit() 
    
    try:
        if platform == "whatsapp":
            if not META_TOKEN: return
            url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
            headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": to_id, "type": "text", "text": {"body": message_text}}
            requests.post(url, json=payload, headers=headers, timeout=2.0)
            
        elif platform == "telegram":
            if not TELEGRAM_TOKEN: return
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": to_id, "text": message_text}
            requests.post(url, json=payload, timeout=2.0)
            
    except Exception as e:
        print(f"⚠️ {platform} Send Failed: {e}")

# --- HELPER: HISTORY ---
def get_db_history(user_id: str, db: Session, limit: int = 10) -> str:
    history_msgs = db.query(Message)\
        .filter(Message.contact_id == str(user_id))\
        .order_by(Message.timestamp.desc())\
        .limit(limit)\
        .all()
    
    context_str = ""
    for m in reversed(history_msgs):
        sender = "User" if m.direction == "inbound" else "AI"
        context_str += f"{sender}: {m.body}\n"
    return context_str

# --- HELPER: OWNER CONFIRMATION LOGIC ---
def process_owner_command(message_text: str, db: Session):
    """
    Handles 'CONFIRM <Student>' command from ANY platform.
    """
    parts = message_text.split()
    if len(parts) < 2:
        return "Format error. Use: CONFIRM <Name>"
        
    student_name = parts[1]
    # Find the user
    target_user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
    
    if target_user:
        # Find their pending order
        order = db.query(Order).filter(Order.user_id == target_user.id, Order.status == "Pending").first()
        if order:
            order.status = "PAID"
            db.commit()
            
            # Find which platform the student is on
            last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
            student_platform = last_msg.platform if last_msg else "whatsapp"
            
            # Notify Student
            send_reply(student_platform, target_user.phone_number, "✅ Payment Confirmed! Your food is being packed.", db)
            return f"Approved {student_name}'s order."
        else:
            return "No pending order found for that student."
    else:
        return "Student not found."

# --- MAIN LOGIC ---
def process_message(platform: str, user_id: str, user_name: str, message_text: str, db: Session):
    
    # 1. Save Inbound
    in_msg = Message(
        platform=platform,
        contact_id=str(user_id),
        direction="inbound",
        body=message_text,
        timestamp=get_current_time_ms()
    )
    db.add(in_msg)
    db.commit()
    
    # 2. User/Owner Check
    # If the sender IS the owner, check for commands
    if str(user_id) == str(OWNER_ID) and "CONFIRM" in message_text.upper():
        reply = process_owner_command(message_text, db)
        send_reply(platform, user_id, reply, db)
        return

    # 3. Create/Fetch Student User
    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 4. Payment Verification Flow
    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Abeg, wetin be the NAME on the account?", db)
        return

    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    
    if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
         # Alert Owner (Dynamic Platform)
         alert = f"💰 ALERT!\nUser: {user_name}\nAcct: {message_text}\nReply 'CONFIRM {user_name}'"
         send_reply(OWNER_PLATFORM, OWNER_ID, alert, db)
         
         # Notify Student
         send_reply(platform, user_id, "Seen! I don tell Auntie.", db)
         return

    # 5. AI Logic
    try:
        history = get_db_history(user_id, db)
        full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"
        
        response_data = order_chain.invoke({"menu": str(settings.MENU), "user_input": full_prompt})
        
        ai_reply = None
        intent = "CHITCHAT" 
        
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
        
        if intent == "ORDER":
            if not pending_order:
                new_order = Order(user_id=user.id, items="Assorted (AI)", total_price=0.0, status="Pending")
                db.add(new_order)
                db.commit()
            
            final_reply = f"{ai_reply}\n\nPay to Opay: 123456.\nReply 'PAID' when done."
            send_reply(platform, user_id, final_reply, db)
        else:
            send_reply(platform, user_id, ai_reply, db)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        send_reply(platform, user_id, "Sorry, network don do anyhow.", db)


# --- WEBHOOKS ---
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "message" in data:
            msg = data["message"]
            chat_id = str(msg["chat"]["id"])
            user_name = msg["from"].get("first_name", "Telegram User")
            text = msg.get("text", "")
            process_message("telegram", chat_id, user_name, text, db)
        return {"status": "ok"}
    except Exception as e:
        print(f"Telegram Error: {e}")
        return {"status": "error"}

@router.post("/webhook")
async def whatsapp_webhook(payload: WhatsAppWebhookSchema, db: Session = Depends(get_db)):
    data = payload.model_dump(by_alias=True)
    try:
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' not in entry or not entry['messages']: return {"status": "ignored"}
            
        message = entry['messages'][0]
        user_phone = message['from']
        message_text = message['text']['body']
        
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

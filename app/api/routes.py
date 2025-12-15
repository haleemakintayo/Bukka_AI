# app/api/routes.py
import os
import requests
import json
import time 
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

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
OWNER_PHONE = "2347048557944" 

# --- HELPER: TIME ---
def get_current_time_ms():
    return int(time.time() * 1000)

# --- ENDPOINT: FRONTEND POLLING (DB VERSION) ---
@router.get("/demo/chats")
async def get_demo_chats(db: Session = Depends(get_db)):
    """
    Fetches the last 50 messages from the Database for the React UI.
    """
    # Get last 50 messages, sorted by time asc (oldest first) so chat looks right
    msgs = db.query(Message).order_by(Message.timestamp.desc()).limit(50).all()
    
    # Convert SQL objects to JSON format for React
    return [
        {
            "id": str(m.id), # React needs string IDs often
            "direction": m.direction,
            "from": m.contact_id if m.direction == "inbound" else "BukkaAI",
            "to": "BukkaAI" if m.direction == "inbound" else m.contact_id,
            "body": m.body,
            "timestamp": m.timestamp,
            "platform": m.platform
        }
        for m in reversed(msgs) # Reverse back to chronological order
    ]

@router.post("/demo/reset")
async def reset_demo_chats(db: Session = Depends(get_db)):
    """Deletes all messages (Optional cleanup)"""
    db.query(Message).delete()
    db.commit()
    return {"status": "cleared"}


# --- HELPER: SAVE & SEND ---
def send_reply(platform: str, to_id: str, message_text: str, db: Session):
    """
    1. Saves Outbound Message to DB.
    2. Sends to Meta/Telegram API.
    """
    print(f"📤 SENDING ({platform}) TO {to_id}: {message_text}")
    
    # A. SAVE TO DB
    new_msg = Message(
        platform=platform,
        contact_id=str(to_id),
        direction="outbound",
        body=message_text,
        timestamp=get_current_time_ms()
    )
    db.add(new_msg)
    db.commit() # Save immediately so UI sees it
    
    # B. SEND VIA API
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

# --- HELPER: FETCH HISTORY (DB VERSION) ---
def get_db_history(user_id: str, db: Session, limit: int = 10) -> str:
    """
    Queries the 'messages' table for this user's chat history.
    """
    # Get last N messages for this user
    history_msgs = db.query(Message)\
        .filter(Message.contact_id == str(user_id))\
        .order_by(Message.timestamp.desc())\
        .limit(limit)\
        .all()
    
    # We fetched them Newest->Oldest, so reverse them for the prompt
    history_msgs = reversed(history_msgs)
    
    context_str = ""
    for m in history_msgs:
        sender = "User" if m.direction == "inbound" else "AI"
        context_str += f"{sender}: {m.body}\n"
        
    print(f"📜 DB HISTORY FOR {user_id}:\n{context_str}")
    return context_str


# --- THE BRAIN 🧠 ---
def process_message(platform: str, user_id: str, user_name: str, message_text: str, db: Session):
    
    # 1. Save Inbound Message to DB
    in_msg = Message(
        platform=platform,
        contact_id=str(user_id),
        direction="inbound",
        body=message_text,
        timestamp=get_current_time_ms()
    )
    db.add(in_msg)
    db.commit() # Commit so it shows up in history immediately
    
    # 2. User Management
    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 3. Payment Verification
    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Abeg, wetin be the NAME on the account?", db)
        return

    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    
    if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
         # Notify Owner
         alert = f"💰 {platform.upper()} ALERT!\nUser: {user_name}\nAcct: {message_text}\nReply 'CONFIRM {user_name}'"
         send_reply("whatsapp", OWNER_PHONE, alert, db)
         
         # Notify User
         send_reply(platform, user_id, "Seen! I don tell Auntie. Wait small.", db)
         return

    # 4. AI Logic
    try:
        # Get History from DB (excluding the current msg we just saved? Actually we just saved it, so we might want to exclude it from prompt or keep it. 
        # Usually LLM likes to see "User: X" at the end. 
        # get_db_history fetches everything including what we just saved. 
        # Let's format the prompt carefully.
        
        history = get_db_history(user_id, db)
        
        # We don't need to append CURRENT MSG manually if it's already in history!
        # But to be safe and explicit for the LLM:
        full_prompt = f"CONVERSATION HISTORY:\n{history}\n(Respond to the last message)"
        
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
        
        # 5. Send Reply
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
        
        # OWNER COMMAND
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
                        send_reply("whatsapp", OWNER_PHONE, f"Approved {student_name}.", db)
                        
                        # Detect Platform
                        # Check last message in DB for this user to find platform
                        last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).first()
                        target_platform = last_msg.platform if last_msg else "whatsapp"
                        
                        send_reply(target_platform, target_user.phone_number, "✅ Payment Confirmed! Your food is being packed.", db)
                    else:
                        send_reply("whatsapp", OWNER_PHONE, "No pending order found.", db)
                else:
                    send_reply("whatsapp", OWNER_PHONE, "Student not found.", db)
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
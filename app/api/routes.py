# app/api/routes.py
import os
import requests
import json
import time 
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Database Imports
from app.core.database import get_db
from app.models.sql_models import User, Order, Message, MenuItem
from app.models.schemas import WhatsAppWebhookSchema

# AI Imports
from app.services.llm_engine import order_chain

router = APIRouter()

# --- CONFIGURATION ---
VERIFY_TOKEN = "blue_chameleon_2025"
META_TOKEN = os.getenv("META_API_TOKEN") 
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") 
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# OWNER SETTINGS
OWNER_PLATFORM = "telegram" 
OWNER_ID = "7490888563" 
OWNER_PHONE_WHATSAPP = "2347048557944" # Keep specifically for WhatsApp checks

# --- HELPER: TIME ---
def get_current_time_ms():
    return int(time.time() * 1000)

# --- HELPER: DYNAMIC MENU (The Magic 🪄) ---
def get_live_menu_text(db: Session) -> str:
    """Fetches available items from DB and formats them for the AI."""
    items = db.query(MenuItem).filter(MenuItem.is_available == True).all()
    
    if not items:
        # Fallback if DB is empty
        return "Jollof Rice (N500), Fried Rice (N500), Chicken (N1000), Water (N100)"
        
    menu_str = ""
    for item in items:
        menu_str += f"- {item.name}: N{int(item.price)}\n"
    return menu_str.strip()

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

# --- HELPER: ADVANCED OWNER COMMANDS ---
def process_owner_command(message_text: str, db: Session):
    """
    Parses commands: CONFIRM, ADD, OUT, IN, MENU
    """
    parts = message_text.split()
    cmd = parts[0].upper()
    
    # 1. CONFIRM PAYMENT
    if cmd == "CONFIRM":
        if len(parts) < 2: return "Usage: CONFIRM <StudentName>"
        student_name = parts[1]
        target_user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
        if target_user:
            order = db.query(Order).filter(Order.user_id == target_user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                # Notify Student
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"✅ Order #{order.id} Confirmed! We are packing it now.", db)
                return f"Approved {student_name}."
            return "No pending order."
        return "Student not found."

    # 2. ADD / UPDATE ITEM (Format: ADD Rice 500)
    elif cmd == "ADD":
        if len(parts) < 3: return "Usage: ADD <ItemName> <Price>"
        try:
            price = float(parts[-1]) # Last part is price
            name = " ".join(parts[1:-1]) # Everything in middle is name
            
            # Upsert Logic
            item = db.query(MenuItem).filter(MenuItem.name.ilike(name)).first()
            if item:
                item.price = price
                item.is_available = True
                action = "Updated"
            else:
                item = MenuItem(name=name, price=price, is_available=True)
                db.add(item)
                action = "Added"
            
            db.commit()
            return f"✅ {action} '{name}' @ N{price}."
        except:
            return "Error. Price must be a number."

    # 3. OUT OF STOCK (Format: OUT Chicken)
    elif cmd == "OUT":
        if len(parts) < 2: return "Usage: OUT <ItemName>"
        name = " ".join(parts[1:])
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = False
            db.commit()
            return f"🚫 '{item.name}' is now OUT OF STOCK."
        return "Item not found."

    # 4. RESTOCK (Format: IN Chicken)
    elif cmd == "IN":
        if len(parts) < 2: return "Usage: IN <ItemName>"
        name = " ".join(parts[1:])
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = True
            db.commit()
            return f"✅ '{item.name}' is back IN STOCK."
        return "Item not found."

    # 5. VIEW MENU
    elif cmd == "MENU":
        return "📜 **Current Menu:**\n" + get_live_menu_text(db)

    return "Unknown Command. Available: CONFIRM, ADD, OUT, IN, MENU"


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
    
    # 2. Check for OWNER COMMANDS
    # We check if sender is Owner ID (Telegram) OR Owner Phone (WhatsApp)
    is_owner = str(user_id) == str(OWNER_ID) or str(user_id) == str(OWNER_PHONE_WHATSAPP)
    
    if is_owner:
        # Check if it looks like a command
        first_word = message_text.split()[0].upper()
        if first_word in ["CONFIRM", "ADD", "OUT", "IN", "DELETE", "MENU"]:
            reply = process_owner_command(message_text, db)
            send_reply(platform, user_id, reply, db)
            return

    # 3. User Management
    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    # 4. Payment Verification Flow
    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Please type the NAME on your bank account.", db)
        return

    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    
    if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
         order_details = pending_order.items or "Unknown"
         total = pending_order.total_price or "0"
         
         alert = (
             f"💰 <b>NEW PAYMENT!</b>\n"
             f"User: {user_name}\n"
             f"Acct: {message_text}\n"
             f"Order #{pending_order.id}: {order_details}\n"
             f"Total: N{total}\n"
             f"Reply 'CONFIRM {user_name}'"
         )
         send_reply(OWNER_PLATFORM, OWNER_ID, alert, db)
         send_reply(platform, user_id, "Seen! I don tell Auntie. Wait small.", db)
         return

    # 5. AI Logic
    try:
        # A. Fetch Dynamic Menu
        live_menu = get_live_menu_text(db) # <--- THIS IS THE UPGRADE
        
        # B. Fetch History
        history = get_db_history(user_id, db)
        full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"
        
        # C. Invoke AI with LIVE MENU
        response_data = order_chain.invoke({"menu": live_menu, "user_input": full_prompt})
        
        ai_reply = None
        intent = "CHITCHAT" 
        order_items_summary = "Assorted"
        order_total = 0.0
        
        if isinstance(response_data, dict):
            ai_reply = response_data.get('message') or response_data.get('text')
            if response_data.get('order'): order_items_summary = response_data.get('order')
            if response_data.get('total'): order_total = float(response_data.get('total'))
            
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
                new_order = Order(
                    user_id=user.id, 
                    items=order_items_summary, 
                    total_price=order_total, 
                    status="Pending"
                )
                db.add(new_order)
                db.commit()
                db.refresh(new_order)
            
            final_reply = f"{ai_reply}\n\nOrder #{new_order.id if 'new_order' in locals() else pending_order.id} Created.\nPay to Opay: 123456.\nReply 'PAID' when done."
            send_reply(platform, user_id, final_reply, db)
        else:
            send_reply(platform, user_id, ai_reply, db)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        send_reply(platform, user_id, "System error. Please try again.", db)


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
        msg = entry['messages'][0]
        user_name = "Student"
        if entry.get('contacts'): user_name = entry['contacts'][0]['profile']['name']
        process_message("whatsapp", msg['from'], user_name, msg['text']['body'], db)
    except Exception as e:
        print(f"WhatsApp Error: {e}")
    return {"status": "received"}

@router.get("/webhook")
async def verify_webhook(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")):
    if mode == "subscribe" and token == VERIFY_TOKEN: return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid Token")
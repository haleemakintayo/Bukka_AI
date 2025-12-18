# app/services/chat_manager.py
import os
import requests
import time
from sqlalchemy.orm import Session
from app.models.sql_models import User, Order, Message, MenuItem
from app.core.config import settings
from app.services.llm_engine import order_chain

# --- CONFIG & SECRETS ---
META_TOKEN = os.getenv("META_API_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# OWNER SETTINGS
OWNER_PLATFORM = "telegram"
OWNER_ID = os.getenv("OWNER_ID", "6094231697") # Default or from ENV
OWNER_PHONE_WHATSAPP = os.getenv("OWNER_PHONE", "2347048557944")

def get_current_time_ms():
    return int(time.time() * 1000)

# --- 1. DYNAMIC MENU LOGIC ---
def get_live_menu_text(db: Session) -> str:
    items = db.query(MenuItem).filter(MenuItem.is_available == True).all()
    if not items:
        return "Jollof Rice (N500), Chicken (N1000), Water (N100)"
    return "\n".join([f"- {item.name}: N{int(item.price)}" for item in items])

# --- 2. SENDING LOGIC (The Hands) ---
def send_reply(platform: str, to_id: str, message_text: str, db: Session):
    print(f"📤 SENDING ({platform}) TO {to_id}: {message_text}")
    
    # Log to DB
    new_msg = Message(
        platform=platform,
        contact_id=str(to_id),
        direction="outbound",
        body=message_text,
        timestamp=get_current_time_ms()
    )
    db.add(new_msg)
    db.commit() 
    
    # Send to API
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

# --- 3. OWNER COMMANDS ---
def process_owner_command(message_text: str, db: Session):
    parts = message_text.split()
    cmd = parts[0].upper()
    
    if cmd == "CONFIRM":
        if len(parts) < 2: return "Usage: CONFIRM <Name>"
        target_user = db.query(User).filter(User.name.ilike(f"%{parts[1]}%")).first()
        if target_user:
            order = db.query(Order).filter(Order.user_id == target_user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                # Notify Student
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"✅ Order #{order.id} Confirmed! We are packing it now.", db)
                return f"Approved {parts[1]}."
            return "No pending order."
        return "Student not found."

    elif cmd == "ADD":
        if len(parts) < 3: return "Usage: ADD <Item> <Price>"
        try:
            price = float(parts[-1])
            name = " ".join(parts[1:-1])
            item = db.query(MenuItem).filter(MenuItem.name.ilike(name)).first()
            if item:
                item.price, item.is_available = price, True
                action = "Updated"
            else:
                db.add(MenuItem(name=name, price=price, is_available=True))
                action = "Added"
            db.commit()
            return f"✅ {action} '{name}' @ N{price}."
        except: return "Price must be a number."

    elif cmd == "OUT":
        name = " ".join(parts[1:])
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = False
            db.commit()
            return f"🚫 '{item.name}' is OUT OF STOCK."
        return "Item not found."
    
    elif cmd == "IN":
        name = " ".join(parts[1:])
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = True
            db.commit()
            return f"✅ '{item.name}' RESTOCKED."
        return "Item not found."

    elif cmd == "MENU":
        return "📜 **Current Menu:**\n" + get_live_menu_text(db)

    return "Unknown Command. Try: CONFIRM, ADD, OUT, IN, MENU"

# --- 4. MAIN PROCESSOR (The Brain) ---
def process_message(platform: str, user_id: str, user_name: str, message_text: str, db: Session):
    # 1. Save Inbound
    db.add(Message(platform=platform, contact_id=str(user_id), direction="inbound", body=message_text, timestamp=get_current_time_ms()))
    db.commit()

    # 2. Owner Check
    is_owner = str(user_id) == str(OWNER_ID) or str(user_id) == str(OWNER_PHONE_WHATSAPP)
    if is_owner and message_text.split()[0].upper() in ["CONFIRM", "ADD", "OUT", "IN", "MENU"]:
        reply = process_owner_command(message_text, db)
        send_reply(platform, user_id, reply, db)
        return

    # 3. User & Order Context
    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user); db.commit(); db.refresh(user)

    # 4. Payment Flow
    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Please type the NAME on your bank account.", db)
        return

    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    if pending_order and len(message_text.split()) < 5 and "CONFIRM" not in message_text.upper():
         alert = f"💰 <b>NEW PAYMENT!</b>\nUser: {user_name}\nAcct: {message_text}\nOrder #{pending_order.id}: {pending_order.items}\nTotal: N{pending_order.total_price}\nReply 'CONFIRM {user_name}'"
         send_reply(OWNER_PLATFORM, OWNER_ID, alert, db)
         send_reply(platform, user_id, "Seen! Wait for confirmation.", db)
         return

    # 5. AI Logic
    try:
        live_menu = get_live_menu_text(db)
        history_msgs = db.query(Message).filter(Message.contact_id == str(user_id)).order_by(Message.timestamp.desc()).limit(10).all()
        history = "\n".join([f"{'User' if m.direction=='inbound' else 'AI'}: {m.body}" for m in reversed(history_msgs)])
        full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"
        
        response = order_chain.invoke({"menu": live_menu, "user_input": full_prompt})
        
        # Parse AI Response
        ai_reply = "I didn't understand."
        intent = "CHITCHAT"
        if isinstance(response, dict):
            ai_reply = response.get('message') or response.get('text') or list(response.values())[0]
            if response.get('status') == 'complete': intent = "ORDER"
        elif isinstance(response, str): ai_reply = response

        if intent == "ORDER":
            if not pending_order:
                # Save Order
                items = response.get('order', 'Assorted') if isinstance(response, dict) else "Assorted"
                total = float(response.get('total', 0)) if isinstance(response, dict) else 0.0
                new_order = Order(user_id=user.id, items=items, total_price=total, status="Pending")
                db.add(new_order); db.commit(); db.refresh(new_order)
                ai_reply += f"\n\nOrder #{new_order.id} Created.\nPay to Opay: 123456.\nReply 'PAID' when done."
        
        send_reply(platform, user_id, ai_reply, db)

    except Exception as e:
        print(f"❌ Error: {e}")
        send_reply(platform, user_id, "Network error. Try again.", db)
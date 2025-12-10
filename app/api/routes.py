# app/api/routes.py
import os
import requests
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.sql_models import User, Order
from app.models.schemas import WhatsAppMessage
from app.services.llm_engine import order_chain
from app.core.config import settings

router = APIRouter()

# --- 1. CONFIGURATION ---
VERIFY_TOKEN = "blue_chameleon_2025"
META_TOKEN = os.getenv("META_API_TOKEN") 
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") 
OWNER_PHONE = "2348012345678"  # REPLACE with actual owner number

# --- 2. HELPER FUNCTIONS (PLACE YOUR CODE HERE) ---

def send_whatsapp_message(to_number: str, message_text: str):
    """
    Sends a message via WhatsApp Cloud API.
    Required by: both Student (replies) and Owner (notifications).
    """
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
    try:
        requests.post(url, json=payload, headers=headers)
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")

def handle_owner_confirmation(db: Session, message_text: str):
    """
    Helper to process the owner's 'CONFIRM EMEKA' command.
    """
    # Logic: Split text "CONFIRM EMEKA" -> Find Emeka -> Mark Paid
    try:
        student_name = message_text.split()[1] # Get name after "CONFIRM"
        # Find student in DB (simplified search)
        user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
        if user:
            # Find their pending order
            order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                # Notify Student their food is ready
                send_whatsapp_message(user.phone_number, "✅ Payment Confirmed! Your food is being packed.")
                return f"Approved {student_name}'s order."
            else:
                return f"{student_name} has no pending orders."
        return "Student not found."
    except:
        return "Format error. Use: CONFIRM <NAME>"

# --- 3. API ROUTES ---

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
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    data = await request.json()
    
    try:
        # Extract Message Info
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' not in entry:
            return {"status": "ignored"}
            
        message = entry['messages'][0]
        user_phone = message['from']
        message_text = message['text']['body']
        
        # --- 4. OWNER LOGIC (PLACE THIS INSIDE THE WEBHOOK) ---
        # We check this FIRST. If it is the owner, we run this block and STOP.
        if user_phone == OWNER_PHONE and "CONFIRM" in message_text.upper():
            reply = handle_owner_confirmation(db, message_text)
            # Send result back to Owner
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, reply)
            return {"status": "owner_action_processed"}

        # --- 5. STUDENT LOGIC (NORMAL FLOW) ---
        
        # Get/Create User
        # ... (User creation logic from previous step) ...
        user_name = entry['contacts'][0]['profile']['name']
        user = db.query(User).filter(User.phone_number == user_phone).first()
        if not user:
            user = User(phone_number=user_phone, name=user_name)
            db.add(user)
            db.commit()

        # Check if Student is reporting payment ("I have paid")
        if "PAID" in message_text.upper():
            # NOTIFY OWNER
            alert_msg = f"💰 PAYMENT ALERT: {user_name} says they paid.\nReply 'CONFIRM {user_name}' to approve."
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, alert_msg)
            
            # Reply to Student
            background_tasks.add_task(send_whatsapp_message, user_phone, "Okay! Asking Auntie to confirm...")
            return {"status": "payment_reported"}

        # Normal AI Chat (Order taking)
        response_data = order_chain.invoke({
            "menu": str(settings.MENU),
            "user_input": message_text
        })
        
        # If order, save to DB and ask for payment...
        if response_data.get('intent') == "ORDER":
            # (Save order logic here...)
            # Add payment instructions to reply
            final_reply = response_data['reply_message'] + "\n\nPay to Opay: 123456. Reply 'PAID' when done."
            background_tasks.add_task(send_whatsapp_message, user_phone, final_reply)
        else:
            background_tasks.add_task(send_whatsapp_message, user_phone, response_data['reply_message'])

    except KeyError:
        pass
        
    return {"status": "received"}
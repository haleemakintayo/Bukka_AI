# app/api/routes.py
import os
import requests
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session

# Database Imports
from app.core.database import get_db
from app.models.sql_models import User, Order
from app.models.schemas import WhatsAppMessage, ConsultantResponse,WhatsAppWebhookSchema

# AI Imports (LangGraph Agent + LCEL Chain)
from app.services.llm_engine import order_chain, consultant_agent
from app.core.config import settings

router = APIRouter()

# --- 1. CONFIGURATION ---
VERIFY_TOKEN = "blue_chameleon_2025"
META_TOKEN = os.getenv("META_API_TOKEN") 
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") 
OWNER_PHONE = "2349060251750"  # REPLACE with actual owner number

# --- 2. HELPER FUNCTIONS ---

def send_whatsapp_message(to_number: str, message_text: str):
    """
    Sends a message via WhatsApp Cloud API.
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
    try:
        student_name = message_text.split()[1] # Get name after "CONFIRM"
        # Find student in DB
        user = db.query(User).filter(User.name.ilike(f"%{student_name}%")).first()
        if user:
            # Find their pending order
            order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                # Notify Student
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
    """Meta verification handshake"""
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid Token")

@router.post("/webhook")
async def whatsapp_webhook(
    payload: WhatsAppWebhookSchema,  # <--- CHANGED: This forces Swagger to show the box
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    """
    MAIN ENTRY POINT: Receives all WhatsApp messages.
    """
    # Convert Pydantic model back to a Python dictionary so your existing logic works
    data = payload.model_dump(by_alias=True)
    
    try:
        # Extract Message Info
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' not in entry:
            return {"status": "ignored"}
            
        message = entry['messages'][0]
        user_phone = message['from']
        message_text = message['text']['body']
        
        # --- A. OWNER LOGIC ---
        if user_phone == OWNER_PHONE and "CONFIRM" in message_text.upper():
            reply = handle_owner_confirmation(db, message_text)
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, reply)
            return {"status": "owner_action_processed"}

        # --- B. STUDENT LOGIC ---
        
        # 1. Get/Create User
        user_name = entry['contacts'][0]['profile']['name']
        user = db.query(User).filter(User.phone_number == user_phone).first()
        if not user:
            user = User(phone_number=user_phone, name=user_name)
            db.add(user)
            db.commit()

        # 2. Check for Payment Report
        if "PAID" in message_text.upper():
            alert_msg = f"💰 PAYMENT ALERT: {user_name} says they paid.\nReply 'CONFIRM {user_name}' to approve."
            background_tasks.add_task(send_whatsapp_message, OWNER_PHONE, alert_msg)
            background_tasks.add_task(send_whatsapp_message, user_phone, "Okay! Asking Auntie to confirm...")
            return {"status": "payment_reported"}

        # 3. AI Order Logic
        response_data = order_chain.invoke({
            "menu": str(settings.MENU),
            "user_input": message_text
        })
        
        if response_data.get('intent') == "ORDER":
            final_reply = response_data['reply_message'] + "\n\nPay to Opay: 123456. Reply 'PAID' when done."
            background_tasks.add_task(send_whatsapp_message, user_phone, final_reply)
        else:
            background_tasks.add_task(send_whatsapp_message, user_phone, response_data['reply_message'])

    except KeyError:
        print(f"⚠️ MISSING DATA KEY: {e}")  # Print the missing key
        print(f"DATA RECEIVED: {data}")      # Print what we actually got
    except Exception as e:
        print(f"Error processing webhook: {e}")
        
    return {"status": "received"}

# --- 4. CONSULTANT ENDPOINT (Updated for LangGraph) ---
@router.post("/consult", response_model=ConsultantResponse)
async def consult_endpoint(payload: WhatsAppMessage):
    """
    Handles Vendor Business Questions using SerpApi + LangGraph.
    """
    try:
        # We define the System Prompt HERE now
        system_instruction = "You are 'Bukka AI', a smart business consultant. Use your tools to find events and prices."
        
        # LangGraph Input: System Message + User Message
        inputs = {
            "messages": [
                ("system", system_instruction),
                ("user", payload.message)
            ]
        }
        
        # Invoke the graph
        response = consultant_agent.invoke(inputs)
        
        # Extract the final AI response (last message)
        final_answer = response["messages"][-1].content
        
        return {"advice": final_answer, "source": "Real-time Web Data"}
    except Exception as e:
        print(f"Consultant Error: {e}")
        return {"advice": "Could not fetch data.", "source": "Error"}
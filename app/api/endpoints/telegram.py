# app/api/endpoints/telegram.py
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.chat_manager import process_message

router = APIRouter()

@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "message" in data:
            msg = data["message"]
            
            # Pass to Brain 🧠
            process_message(
                platform="telegram",
                user_id=str(msg["chat"]["id"]),
                user_name=msg.get("from", {}).get("first_name", "User"),
                message_text=msg.get("text", ""),
                db=db
            )
        return {"status": "ok"}
    except Exception as e:
        print(f"Telegram Error: {e}")
        return {"status": "error"}
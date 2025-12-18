# app/api/endpoints/demo.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.sql_models import Message

router = APIRouter()

@router.get("/chats")
async def get_demo_chats(db: Session = Depends(get_db)):
    msgs = db.query(Message).order_by(Message.timestamp.desc()).limit(50).all()
    return [
        {
            "id": str(m.id),
            "direction": m.direction,
            "from": m.contact_id if m.direction == "inbound" else "BukkaAI",
            "body": m.body,
            "timestamp": m.timestamp,
            "platform": m.platform
        } for m in reversed(msgs)
    ]

@router.post("/reset")
async def reset_demo_chats(db: Session = Depends(get_db)):
    db.query(Message).delete()
    db.commit()
    return {"status": "cleared"}
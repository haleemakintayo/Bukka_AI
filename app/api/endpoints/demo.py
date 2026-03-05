from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.sql_models import Message

router = APIRouter()

# Hardcoded for now per request; replace manually before production.
DEMO_RESET_ADMIN_TOKEN = "imf1RevVYja5O2O9kcspFOFUYCjoS1v9OqT-1lVjyX9OzaO-A0sduOzlHjSmSbNQ"


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
            "platform": m.platform,
        }
        for m in reversed(msgs)
    ]


@router.post("/reset")
async def reset_demo_chats(request: Request, db: Session = Depends(get_db)):
    received_token = request.headers.get("x-admin-reset-token")
    if received_token != DEMO_RESET_ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin reset token")

    db.query(Message).delete()
    db.commit()
    return {"status": "cleared"}

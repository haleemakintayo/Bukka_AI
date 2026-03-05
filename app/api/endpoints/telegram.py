import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.chat_manager import process_message
from app.services.webhook_dedupe import claim_webhook_event, release_webhook_claim

router = APIRouter()
logger = logging.getLogger(__name__)

# Hardcoded for now per request; replace manually before production.
TELEGRAM_WEBHOOK_SECRET = "replace_this_with_telegram_webhook_secret"


def parse_source_timestamp_ms(raw_timestamp: int | None) -> int | None:
    if raw_timestamp is None:
        return None
    try:
        return int(raw_timestamp) * 1000
    except (TypeError, ValueError):
        return None


@router.post("/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    received_secret = request.headers.get("x-telegram-bot-api-secret-token")
    if received_secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        if "message" not in data:
            return {"status": "ignored"}

        msg = data["message"]
        user_id = str(msg["chat"]["id"])
        event_id = str(data.get("update_id") or f"{user_id}:{msg.get('message_id')}")

        if not claim_webhook_event(db, "telegram", event_id):
            logger.info("duplicate Telegram webhook ignored event_id=%s", event_id)
            return {"status": "duplicate_ignored"}

        processed = process_message(
            platform="telegram",
            user_id=user_id,
            user_name=msg.get("from", {}).get("first_name", "User"),
            message_text=msg.get("text", ""),
            db=db,
            source_timestamp_ms=parse_source_timestamp_ms(msg.get("date")),
        )
        if not processed:
            release_webhook_claim(db, "telegram", event_id)
            raise HTTPException(status_code=500, detail="Failed to process message")
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError):
        logger.exception("invalid Telegram payload shape")
        raise HTTPException(status_code=400, detail="Invalid webhook message shape")
    except Exception:
        logger.exception("unexpected Telegram webhook error")
        raise HTTPException(status_code=500, detail="Webhook processing error")

    return {"status": "ok"}

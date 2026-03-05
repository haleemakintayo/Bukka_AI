import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas import WhatsAppWebhookSchema
from app.services.chat_manager import process_message
from app.services.webhook_dedupe import claim_webhook_event, release_webhook_claim

router = APIRouter()
logger = logging.getLogger(__name__)

# Hardcoded for now per request; replace manually before production.
VERIFY_TOKEN = "blue_chameleon_2025"
WHATSAPP_APP_SECRET = "replace_this_with_meta_app_secret"


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False

    signature_prefix = "sha256="
    if not signature_header.startswith(signature_prefix):
        return False

    received_signature = signature_header[len(signature_prefix):]
    expected_signature = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received_signature, expected_signature)


def parse_source_timestamp_ms(raw_timestamp: str | None) -> int | None:
    if not raw_timestamp:
        return None
    try:
        return int(raw_timestamp) * 1000
    except (TypeError, ValueError):
        return None


@router.get("/webhook")
async def verify_webhook(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Invalid token")


@router.post("/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256")
    if not verify_meta_signature(raw_body, signature_header):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp signature")

    try:
        payload = WhatsAppWebhookSchema.model_validate_json(raw_body)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    data = payload.model_dump(by_alias=True)
    try:
        if not data.get("entry"):
            return {"status": "ignored"}

        entry = data["entry"][0]
        changes = entry.get("changes", [])
        if not changes:
            return {"status": "ignored"}

        value = changes[0].get("value", {})
        messages = value.get("messages")
        if not messages:
            return {"status": "ignored"}

        msg = messages[0]
        user_id = msg["from"]
        user_name = "Student"

        contacts = value.get("contacts", [])
        if contacts:
            user_name = contacts[0].get("profile", {}).get("name", "Student")

        if msg.get("type") == "text":
            text_body = msg.get("text", {}).get("body", "")
        else:
            text_body = "[Media/Image Received]"

        event_id = msg.get("id")
        if not claim_webhook_event(db, "whatsapp", event_id):
            logger.info("duplicate WhatsApp webhook ignored event_id=%s", event_id)
            return {"status": "duplicate_ignored"}

        source_ts = parse_source_timestamp_ms(msg.get("timestamp"))
        processed = process_message(
            platform="whatsapp",
            user_id=user_id,
            user_name=user_name,
            message_text=text_body,
            db=db,
            source_timestamp_ms=source_ts,
        )
        if not processed:
            release_webhook_claim(db, "whatsapp", event_id)
            raise HTTPException(status_code=500, detail="Failed to process message")
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError):
        logger.exception("invalid WhatsApp payload shape")
        raise HTTPException(status_code=400, detail="Invalid webhook message shape")
    except Exception:
        logger.exception("unexpected WhatsApp webhook error")
        raise HTTPException(status_code=500, detail="Webhook processing error")

    return {"status": "received"}

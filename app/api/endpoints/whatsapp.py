import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas import WhatsAppWebhookSchema
from app.services.chat_manager import process_message
from app.services.webhook_dedupe import claim_webhook_event, release_webhook_claim

router = APIRouter()
logger = logging.getLogger(__name__)

# Load from environment variables; fallback to defaults if not set
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "blue_chameleon_2025")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "replace_this_with_meta_app_secret")


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
    """
    Webhook Verification: Meta sends this during webhook registration.
    
    Query params:
    - hub.mode: "subscribe" (indicates this is a verification request)
    - hub.verify_token: Your secret token from environment
    - hub.challenge: Random string to echo back
    
    If token matches WHATSAPP_VERIFY_TOKEN env var, return the challenge as plain text.
    Otherwise, return 403 Forbidden.
    """
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge, status_code=200)
    
    logger.warning("Webhook verification failed - invalid token or mode")
    raise HTTPException(status_code=403, detail="Invalid verification token or mode")


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Receive incoming WhatsApp messages from Meta's Cloud API.
    
    CRITICAL FASTAPI PATTERN:
    - Return 200 OK immediately to Meta (they retry if no response within ~30s)
    - Queue message processing in BackgroundTasks
    - Safe parsing for status updates (delivered/read receipts)
    """
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256")
    
    # Verify Meta signature
    if not verify_meta_signature(raw_body, signature_header):
        logger.warning("Invalid WhatsApp signature received")
        raise HTTPException(status_code=403, detail="Invalid WhatsApp signature")

    # Parse and validate webhook payload
    try:
        payload = WhatsAppWebhookSchema.model_validate_json(raw_body)
    except ValidationError as e:
        logger.warning("Invalid webhook payload: %s", e)
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    # Queue the message processing in the background
    background_tasks.add_task(
        _process_whatsapp_message,
        payload_dict=payload.model_dump(by_alias=True),
        db=db,
    )

    # Return 200 OK immediately to Meta
    return {"status": "received"}


async def _process_whatsapp_message(payload_dict: dict, db: Session):
    """
    Background task: Process the WhatsApp message.
    
    Safely extracts: wa_id (sender's phone), name (profile name), text.body (message).
    Handles status updates (delivered/read) gracefully without crashing.
    """
    try:
        # Safe nested navigation - handles status updates without 'messages' field
        entries = payload_dict.get("entry", [])
        if not entries:
            logger.debug("No entries in webhook payload")
            return

        entry = entries[0]
        changes = entry.get("changes", [])
        if not changes:
            logger.debug("No changes in entry")
            return

        value = changes[0].get("value", {})
        
        # Status updates (delivered/read) have no 'messages' field - ignore gracefully
        messages = value.get("messages")
        if not messages:
            logger.debug("No messages in value (possibly a status update)")
            return

        msg = messages[0]
        user_id = msg.get("from")
        if not user_id:
            logger.warning("Message missing 'from' field")
            return

        # Extract contact name from contacts array (safe .get())
        user_name = "Student"  # Default fallback
        contacts = value.get("contacts", [])
        if contacts:
            contact_profile = contacts[0].get("profile", {})
            user_name = contact_profile.get("name", "Student")

        # Extract message text (safe handling for different message types)
        message_type = msg.get("type", "text")
        if message_type == "text":
            text_body = msg.get("text", {}).get("body", "")
        else:
            # Handle media, image, audio, etc.
            text_body = f"[{message_type.upper()} received - not yet supported]"

        if not text_body:
            logger.debug("Empty message body")
            return

        # Extract message ID for deduplication
        event_id = msg.get("id")
        if not event_id:
            logger.warning("Message missing 'id' field")
            return

        # Deduplication: check if we've already processed this message
        if not claim_webhook_event(db, "whatsapp", event_id):
            logger.info("Duplicate WhatsApp webhook ignored - event_id=%s", event_id)
            return

        # Extract timestamp and process the message
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
            logger.error("Failed to process message for user %s", user_id)
            release_webhook_claim(db, "whatsapp", event_id)
            return

        logger.info(
            "WhatsApp message processed - user=%s, text=%s",
            user_id,
            text_body[:50],
        )

    except (KeyError, TypeError, ValueError) as e:
        logger.exception("Invalid WhatsApp payload shape: %s", e)
    except Exception as e:
        logger.exception("Unexpected error processing WhatsApp message: %s", e)

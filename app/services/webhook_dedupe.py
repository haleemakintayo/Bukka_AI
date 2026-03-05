import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sql_models import ProcessedWebhookEvent


def claim_webhook_event(db: Session, platform: str, external_event_id: str | None) -> bool:
    if not external_event_id:
        return True

    event = ProcessedWebhookEvent(
        platform=platform,
        external_event_id=external_event_id,
        claimed_at=int(time.time() * 1000),
    )
    db.add(event)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def release_webhook_claim(db: Session, platform: str, external_event_id: str | None) -> None:
    if not external_event_id:
        return

    db.query(ProcessedWebhookEvent).filter(
        ProcessedWebhookEvent.platform == platform,
        ProcessedWebhookEvent.external_event_id == external_event_id,
    ).delete()
    db.commit()

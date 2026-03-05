import os
import logging
import requests
import time
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy.orm import Session

from app.models.sql_models import User, Order, Message, MenuItem
from app.services.llm_engine import order_chain

# --- CONFIG & SECRETS ---
META_TOKEN = os.getenv("META_API_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# OWNER SETTINGS
OWNER_PLATFORM = (os.getenv("OWNER_PLATFORM") or "telegram").strip().lower()
OWNER_ID = os.getenv("OWNER_ID")
OWNER_PHONE_WHATSAPP = os.getenv("OWNER_PHONE")

logger = logging.getLogger(__name__)

OWNER_HELP_TEXT = (
    "Vendor commands:\n"
    "/menu\n"
    "/add <item name> | <price>\n"
    "/out <item name>\n"
    "/in <item name>\n"
    "/confirm <order_id>\n"
    "/help\n\n"
    "Examples:\n"
    "/add Jollof Rice | 500\n"
    "/out Chicken\n"
    "/confirm 105"
)


def get_current_time_ms():
    return int(time.time() * 1000)


def owner_destination() -> tuple[str, str] | None:
    if OWNER_PLATFORM == "telegram":
        if OWNER_ID:
            return ("telegram", str(OWNER_ID))
        return None
    if OWNER_PLATFORM == "whatsapp":
        if OWNER_PHONE_WHATSAPP:
            return ("whatsapp", str(OWNER_PHONE_WHATSAPP))
        return None

    if OWNER_ID:
        return ("telegram", str(OWNER_ID))
    if OWNER_PHONE_WHATSAPP:
        return ("whatsapp", str(OWNER_PHONE_WHATSAPP))
    return None


def is_owner_sender(platform: str, user_id: str) -> bool:
    if platform == "telegram":
        return bool(OWNER_ID) and str(user_id) == str(OWNER_ID)
    if platform == "whatsapp":
        return bool(OWNER_PHONE_WHATSAPP) and str(user_id) == str(OWNER_PHONE_WHATSAPP)
    return False


def get_live_menu_items(db: Session):
    return db.query(MenuItem).filter(MenuItem.is_available == True).all()


def get_live_menu_text(db: Session) -> str:
    items = get_live_menu_items(db)
    if not items:
        return "Jollof Rice (N500), Chicken (N1000), Water (N100)"
    return "\n".join([f"- {item.name}: N{item.price or 0}" for item in items])


def parse_naira_amount(raw_amount: str) -> int:
    amount = Decimal(raw_amount)
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_text(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return " ".join(cleaned.split())


def resolve_menu_item(raw_item: str, menu_items: list[MenuItem]) -> MenuItem | None:
    target = normalize_text(raw_item)
    if not target:
        return None

    for item in menu_items:
        item_name = normalize_text(item.name)
        if target == item_name or target in item_name or item_name in target:
            return item

    target_tokens = set(target.split())
    best_item = None
    best_score = 0
    for item in menu_items:
        item_tokens = set(normalize_text(item.name).split())
        score = len(target_tokens & item_tokens)
        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score > 0 else None


def build_order_from_extraction(extraction: dict, db: Session):
    menu_items = get_live_menu_items(db)
    extracted_items = extraction.get("items") or []
    extracted_qty = extraction.get("qty") or []
    line_items = []
    unmatched_items = []

    for index, raw_item in enumerate(extracted_items):
        qty = extracted_qty[index] if index < len(extracted_qty) else 1
        try:
            qty = int(qty)
            if qty < 1:
                qty = 1
        except (TypeError, ValueError):
            qty = 1

        menu_item = resolve_menu_item(raw_item, menu_items)
        if not menu_item:
            unmatched_items.append(raw_item)
            continue

        unit_price = int(menu_item.price or 0)
        line_total = unit_price * qty
        line_items.append(
            {
                "name": menu_item.name,
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    total = sum(item["line_total"] for item in line_items)
    return line_items, total, unmatched_items


def format_line_items(line_items: list[dict]) -> str:
    return ", ".join([f"{item['qty']} x {item['name']}" for item in line_items])


def send_reply(platform: str, to_id: str, message_text: str, db: Session):
    logger.info("sending outbound message platform=%s to=%s", platform, to_id)

    new_msg = Message(
        platform=platform,
        contact_id=str(to_id),
        direction="outbound",
        body=message_text,
        timestamp=get_current_time_ms(),
    )
    db.add(new_msg)
    db.commit()

    try:
        if platform == "whatsapp":
            if not META_TOKEN:
                return
            url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
            headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": to_id, "type": "text", "text": {"body": message_text}}
            response = requests.post(url, json=payload, headers=headers, timeout=4.0)
            response.raise_for_status()
        elif platform == "telegram":
            if not TELEGRAM_TOKEN:
                return
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": to_id, "text": message_text}
            response = requests.post(url, json=payload, timeout=4.0)
            response.raise_for_status()
    except requests.RequestException:
        logger.exception("outbound message delivery failed platform=%s to=%s", platform, to_id)


def parse_owner_command(message_text: str) -> dict | None:
    raw = (message_text or "").strip()
    if not raw:
        return None

    # Preferred format: slash commands.
    if raw.startswith("/"):
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg_text = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            return {"cmd": "HELP"}
        if cmd == "/menu":
            return {"cmd": "MENU"}
        if cmd == "/out":
            return {"cmd": "OUT", "name": arg_text}
        if cmd == "/in":
            return {"cmd": "IN", "name": arg_text}
        if cmd == "/confirm":
            return {"cmd": "CONFIRM", "target": arg_text}
        if cmd == "/add":
            # Allow: /add Item Name | 500
            if "|" in arg_text:
                name, price = arg_text.rsplit("|", 1)
                return {"cmd": "ADD", "name": name.strip(), "price": price.strip()}
            # Fallback: /add Item Name 500
            match = re.match(r"(.+)\s+([0-9]+(?:\.[0-9]+)?)$", arg_text)
            if match:
                return {"cmd": "ADD", "name": match.group(1).strip(), "price": match.group(2).strip()}
            return {"cmd": "ADD", "name": "", "price": ""}
        return {"cmd": "UNKNOWN"}

    # Legacy format support: only if command token is explicitly uppercase.
    first = raw.split()[0]
    if first.isupper() and first in {"HELP", "MENU", "OUT", "IN", "CONFIRM", "ADD"}:
        parts = raw.split(maxsplit=1)
        arg_text = parts[1].strip() if len(parts) > 1 else ""
        if first == "HELP":
            return {"cmd": "HELP"}
        if first == "MENU":
            return {"cmd": "MENU"}
        if first == "OUT":
            return {"cmd": "OUT", "name": arg_text}
        if first == "IN":
            return {"cmd": "IN", "name": arg_text}
        if first == "CONFIRM":
            return {"cmd": "CONFIRM", "target": arg_text}
        if first == "ADD":
            if "|" in arg_text:
                name, price = arg_text.rsplit("|", 1)
                return {"cmd": "ADD", "name": name.strip(), "price": price.strip()}
            match = re.match(r"(.+)\s+([0-9]+(?:\.[0-9]+)?)$", arg_text)
            if match:
                return {"cmd": "ADD", "name": match.group(1).strip(), "price": match.group(2).strip()}
            return {"cmd": "ADD", "name": "", "price": ""}

    return None


def process_owner_command(command: dict, db: Session):
    cmd = command.get("cmd")

    if cmd == "CONFIRM":
        target = (command.get("target") or "").strip()
        if not target:
            return "Usage: /confirm <order_id>\n\n" + OWNER_HELP_TEXT

        if target.isdigit():
            order = db.query(Order).filter(Order.id == int(target), Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                target_user = db.query(User).filter(User.id == order.user_id).first()
                if not target_user:
                    return f"Order #{order.id} marked PAID, but user record is missing."
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"Order #{order.id} confirmed. We are packing it now.", db)
                return f"Approved order #{order.id}."
            return f"No pending order found for id {target}."

        # Fallback by name for convenience, but warn if ambiguous.
        matches = db.query(User).filter(User.name.ilike(f"%{target}%")).all()
        if len(matches) > 1:
            sample = ", ".join([f"{u.name}({u.id})" for u in matches[:5]])
            return f"Multiple users match '{target}'. Use /confirm <order_id>.\nMatches: {sample}"
        if len(matches) == 1:
            target_user = matches[0]
            order = db.query(Order).filter(Order.user_id == target_user.id, Order.status == "Pending").first()
            if order:
                order.status = "PAID"
                db.commit()
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"Order #{order.id} confirmed. We are packing it now.", db)
                return f"Approved order #{order.id} for {target_user.name}."
            return f"No pending order for {target_user.name}."
        return f"No user found for '{target}'."

    if cmd == "ADD":
        name = (command.get("name") or "").strip()
        price_raw = (command.get("price") or "").strip()
        if not name or not price_raw:
            return "Usage: /add <item name> | <price>\nExample: /add Jollof Rice | 500"
        try:
            price = parse_naira_amount(price_raw)
            item = db.query(MenuItem).filter(MenuItem.name.ilike(name)).first()
            if item:
                item.price = price
                item.is_available = True
                action = "Updated"
            else:
                db.add(MenuItem(name=name, price=price, is_available=True))
                action = "Added"
            db.commit()
            return f"{action} '{name}' @ N{price}."
        except (TypeError, ValueError, InvalidOperation):
            return "Price must be a number."

    if cmd == "OUT":
        name = (command.get("name") or "").strip()
        if not name:
            return "Usage: /out <item name>"
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = False
            db.commit()
            return f"'{item.name}' is OUT OF STOCK."
        return "Item not found."

    if cmd == "IN":
        name = (command.get("name") or "").strip()
        if not name:
            return "Usage: /in <item name>"
        item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{name}%")).first()
        if item:
            item.is_available = True
            db.commit()
            return f"'{item.name}' RESTOCKED."
        return "Item not found."

    if cmd == "MENU":
        return "Current Menu:\n" + get_live_menu_text(db)

    if cmd == "HELP":
        return OWNER_HELP_TEXT

    return "Unknown command.\n\n" + OWNER_HELP_TEXT


def process_message(
    platform: str,
    user_id: str,
    user_name: str,
    message_text: str,
    db: Session,
    source_timestamp_ms: int | None = None,
) -> bool:
    db.add(
        Message(
            platform=platform,
            contact_id=str(user_id),
            direction="inbound",
            body=message_text,
            timestamp=source_timestamp_ms if source_timestamp_ms else get_current_time_ms(),
        )
    )
    db.commit()

    is_owner = is_owner_sender(platform, user_id)
    words = message_text.split()
    owner_cmd = parse_owner_command(message_text) if is_owner else None
    if is_owner and owner_cmd:
        reply = process_owner_command(owner_cmd, db)
        send_reply(platform, user_id, reply, db)
        return True

    user = db.query(User).filter(User.phone_number == str(user_id)).first()
    if not user:
        user = User(phone_number=str(user_id), name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)

    if "PAID" in message_text.upper() and len(message_text) < 20:
        send_reply(platform, user_id, "Okay! Please type the NAME on your bank account.", db)
        return True

    pending_order = db.query(Order).filter(Order.user_id == user.id, Order.status == "Pending").first()
    if pending_order and len(words) < 5 and "CONFIRM" not in message_text.upper():
        alert = (
            f"NEW PAYMENT\n"
            f"User: {user_name}\n"
            f"Acct: {message_text}\n"
            f"Order #{pending_order.id}: {pending_order.items}\n"
            f"Total: N{int(pending_order.total_price or 0)}\n"
            f"Use /confirm {pending_order.id}"
        )
        owner_target = owner_destination()
        if owner_target:
            owner_platform, owner_contact = owner_target
            send_reply(owner_platform, owner_contact, alert, db)
        else:
            logger.warning("owner destination not configured; skipping owner alert")
        send_reply(platform, user_id, "Seen! Wait for confirmation.", db)
        return True

    try:
        live_menu = get_live_menu_text(db)
        history_msgs = (
            db.query(Message)
            .filter(Message.contact_id == str(user_id))
            .order_by(Message.timestamp.desc())
            .limit(10)
            .all()
        )
        history = "\n".join([f"{'User' if m.direction == 'inbound' else 'AI'}: {m.body}" for m in reversed(history_msgs)])
        full_prompt = f"HISTORY:\n{history}\nCURRENT MSG: {message_text}"

        response = order_chain.invoke({"menu": live_menu, "user_input": full_prompt})
        extraction = response if isinstance(response, dict) else {}
        intent = str(extraction.get("intent", "unknown")).lower().strip()

        if intent == "payment":
            send_reply(platform, user_id, "Okay! Please type the NAME on your bank account.", db)
            return True

        if intent == "inquiry":
            extracted_items = extraction.get("items") or []
            available_items = get_live_menu_items(db)
            if not extracted_items:
                send_reply(platform, user_id, f"Current menu:\n{live_menu}", db)
                return True

            price_lines = []
            for raw_item in extracted_items:
                match = resolve_menu_item(raw_item, available_items)
                if match:
                    price_lines.append(f"- {match.name}: N{match.price or 0}")

            if price_lines:
                send_reply(platform, user_id, "Here are the prices:\n" + "\n".join(price_lines), db)
            else:
                send_reply(platform, user_id, f"I could not find that item. Current menu:\n{live_menu}", db)
            return True

        if intent == "order":
            line_items, total, unmatched = build_order_from_extraction(extraction, db)
            if not line_items:
                send_reply(platform, user_id, f"I could not identify valid menu items.\nCurrent menu:\n{live_menu}", db)
                return True

            summary = format_line_items(line_items)
            if pending_order:
                pending_order.items = summary
                pending_order.total_price = total
                pending_order.status = "Pending"
                db.commit()
                order_id = pending_order.id
            else:
                new_order = Order(user_id=user.id, items=summary, total_price=total, status="Pending")
                db.add(new_order)
                db.commit()
                db.refresh(new_order)
                order_id = new_order.id

            unmatched_text = ""
            if unmatched:
                unmatched_text = "\nUnavailable/unclear items ignored: " + ", ".join(unmatched)

            reply = (
                f"Order #{order_id} captured: {summary}.\n"
                f"Total: N{total}.\n"
                "Pay to Opay: 123456.\n"
                "Reply 'PAID' when done."
                f"{unmatched_text}"
            )
            send_reply(platform, user_id, reply, db)
            return True

        send_reply(platform, user_id, f"I can help with orders and prices.\nCurrent menu:\n{live_menu}", db)
        return True
    except Exception:
        logger.exception("message processing failed platform=%s user_id=%s", platform, user_id)
        send_reply(platform, user_id, "Network error. Try again.", db)
        return False

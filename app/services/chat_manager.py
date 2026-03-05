import os
import logging
import requests
import time
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.sql_models import User, Order, Message, MenuItem, StockMovement
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
    "/menu or menu\n"
    "/add <item name> | <price> [| <opening_stock> [| <reorder_level>]] or add ...\n"
    "/out <item name> or out ...\n"
    "/in <item name> (slash form recommended)\n"
    "/confirm <order_id> or confirm ...\n"
    "/stock or stock\n"
    "/stock add <item> | <qty> or stock add ...\n"
    "/stock use <item> | <qty> or stock use ...\n"
    "/stock set <item> | <qty> or stock set ...\n"
    "/stock waste <item> | <qty> | <reason> or stock waste ...\n"
    "/stock level <item> | <qty> or stock level ...\n"
    "/help or help\n\n"
    "Examples:\n"
    "/add Jollof Rice | 500\n"
    "add Jollof Rice | 500\n"
    "/out Chicken\n"
    "confirm 105\n"
    "/stock set Jollof Rice | 20\n"
    "/stock waste Chicken | 2 | Burnt batch"
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
    return db.query(MenuItem).filter(
        MenuItem.is_available == True,
        or_(MenuItem.stock_qty.is_(None), MenuItem.stock_qty > 0),
    ).all()


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


def parse_non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise ValueError("Value cannot be negative")
    return value


def parse_name_qty(arg_text: str) -> tuple[str, str] | None:
    if "|" in arg_text:
        name, qty = arg_text.rsplit("|", 1)
        return name.strip(), qty.strip()
    match = re.match(r"(.+)\s+([0-9]+)$", arg_text.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None


def parse_name_qty_reason(arg_text: str) -> tuple[str, str, str] | None:
    if "|" in arg_text:
        parts = [part.strip() for part in arg_text.split("|")]
        if len(parts) >= 3:
            return parts[0], parts[1], " | ".join(parts[2:])
        return None
    return None


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


def record_stock_movement(
    db: Session,
    item: MenuItem,
    movement_type: str,
    qty: int,
    actor_platform: str | None,
    actor_id: str | None,
    reason: str | None = None,
):
    db.add(
        StockMovement(
            item_id=item.id,
            movement_type=movement_type,
            qty=qty,
            reason=reason,
            actor_platform=actor_platform,
            actor_id=str(actor_id) if actor_id else None,
            timestamp=get_current_time_ms(),
        )
    )


def low_stock_message(item: MenuItem) -> str | None:
    if item.stock_qty is None or item.reorder_level is None:
        return None
    if item.stock_qty <= item.reorder_level:
        return f"{item.name} low stock ({item.stock_qty} left, reorder level {item.reorder_level})"
    return None


def parse_order_summary_items(summary: str | None) -> list[tuple[str, int]]:
    if not summary:
        return []
    parsed = []
    for segment in summary.split(","):
        part = segment.strip()
        match = re.match(r"^(\d+)\s*x\s*(.+)$", part, flags=re.IGNORECASE)
        if not match:
            continue
        qty = int(match.group(1))
        name = match.group(2).strip()
        if qty > 0 and name:
            parsed.append((name, qty))
    return parsed


def apply_sale_stock_deduction(
    db: Session,
    order: Order,
    actor_platform: str,
    actor_id: str,
) -> tuple[bool, str, list[str]]:
    items_to_deduct = parse_order_summary_items(order.items)
    if not items_to_deduct:
        return True, "", []

    menu_items = db.query(MenuItem).all()
    unresolved = []
    insufficient = []
    resolved = []

    for item_name, qty in items_to_deduct:
        item = resolve_menu_item(item_name, menu_items)
        if not item:
            unresolved.append(item_name)
            continue
        resolved.append((item, qty))
        if item.stock_qty is not None and item.stock_qty < qty:
            insufficient.append(f"{item.name} (need {qty}, have {item.stock_qty})")

    if insufficient:
        message = "Cannot confirm order due to insufficient stock:\n" + "\n".join([f"- {x}" for x in insufficient])
        return False, message, []

    low_alerts = []
    for item, qty in resolved:
        if item.stock_qty is None:
            continue
        item.stock_qty -= qty
        if item.stock_qty <= 0:
            item.stock_qty = 0
            item.is_available = False
        record_stock_movement(
            db=db,
            item=item,
            movement_type="sale",
            qty=qty,
            actor_platform=actor_platform,
            actor_id=actor_id,
            reason=f"Order #{order.id}",
        )
        low_alert = low_stock_message(item)
        if low_alert:
            low_alerts.append(low_alert)

    unresolved_msg = ""
    if unresolved:
        unresolved_msg = "Unmapped items skipped for stock deduction: " + ", ".join(unresolved)
    return True, unresolved_msg, low_alerts


def format_stock_snapshot(items: list[MenuItem]) -> str:
    if not items:
        return "No menu items found."

    lines = []
    def sort_key(item: MenuItem):
        if item.stock_qty is None:
            return (2, item.name.lower())
        low = 1 if (item.reorder_level is not None and item.stock_qty <= item.reorder_level) else 0
        return (low, item.stock_qty, item.name.lower())

    for item in sorted(items, key=sort_key):
        stock_text = "untracked" if item.stock_qty is None else str(item.stock_qty)
        level_text = "-" if item.reorder_level is None else str(item.reorder_level)
        low_flag = ""
        if item.stock_qty is not None and item.reorder_level is not None and item.stock_qty <= item.reorder_level:
            low_flag = " [LOW]"
        lines.append(f"- {item.name}: stock={stock_text}, level={level_text}, price=N{item.price or 0}{low_flag}")
    return "Stock Snapshot:\n" + "\n".join(lines)


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


def awaiting_payment_name_input(db: Session, platform: str, user_id: str) -> bool:
    last_outbound = (
        db.query(Message)
        .filter(
            Message.platform == platform,
            Message.contact_id == str(user_id),
            Message.direction == "outbound",
        )
        .order_by(Message.timestamp.desc())
        .first()
    )
    if not last_outbound or not last_outbound.body:
        return False
    marker = "type the name on your bank account"
    return marker in last_outbound.body.lower()


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
            # Allow: /add Item Name | 500 | 20 | 5
            if "|" in arg_text:
                fields = [field.strip() for field in arg_text.split("|")]
                if len(fields) >= 2:
                    return {
                        "cmd": "ADD",
                        "name": fields[0],
                        "price": fields[1],
                        "stock_qty": fields[2] if len(fields) > 2 else "",
                        "reorder_level": fields[3] if len(fields) > 3 else "",
                    }
            # Fallback: /add Item Name 500
            match = re.match(r"(.+)\s+([0-9]+(?:\.[0-9]+)?)$", arg_text)
            if match:
                return {"cmd": "ADD", "name": match.group(1).strip(), "price": match.group(2).strip()}
            return {"cmd": "ADD", "name": "", "price": ""}
        if cmd == "/stock":
            if not arg_text:
                return {"cmd": "STOCK_SNAPSHOT"}
            parts = arg_text.split(maxsplit=1)
            action = parts[0].lower()
            tail = parts[1].strip() if len(parts) > 1 else ""

            if action == "add":
                return {"cmd": "STOCK_ADD", "arg": tail}
            if action == "use":
                return {"cmd": "STOCK_USE", "arg": tail}
            if action == "set":
                return {"cmd": "STOCK_SET", "arg": tail}
            if action == "waste":
                return {"cmd": "STOCK_WASTE", "arg": tail}
            if action == "level":
                return {"cmd": "STOCK_LEVEL", "arg": tail}
            return {"cmd": "UNKNOWN"}
        return {"cmd": "UNKNOWN"}

    # Legacy format support: only if command token is explicitly uppercase.
    first = raw.split()[0]
    if first.isupper() and first in {"HELP", "MENU", "OUT", "IN", "CONFIRM", "ADD", "STOCK"}:
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
                fields = [field.strip() for field in arg_text.split("|")]
                if len(fields) >= 2:
                    return {
                        "cmd": "ADD",
                        "name": fields[0],
                        "price": fields[1],
                        "stock_qty": fields[2] if len(fields) > 2 else "",
                        "reorder_level": fields[3] if len(fields) > 3 else "",
                    }
            match = re.match(r"(.+)\s+([0-9]+(?:\.[0-9]+)?)$", arg_text)
            if match:
                return {"cmd": "ADD", "name": match.group(1).strip(), "price": match.group(2).strip()}
            return {"cmd": "ADD", "name": "", "price": ""}
        if first == "STOCK":
            if not arg_text:
                return {"cmd": "STOCK_SNAPSHOT"}
            parts = arg_text.split(maxsplit=1)
            action = parts[0].lower()
            tail = parts[1].strip() if len(parts) > 1 else ""
            if action == "add":
                return {"cmd": "STOCK_ADD", "arg": tail}
            if action == "use":
                return {"cmd": "STOCK_USE", "arg": tail}
            if action == "set":
                return {"cmd": "STOCK_SET", "arg": tail}
            if action == "waste":
                return {"cmd": "STOCK_WASTE", "arg": tail}
            if action == "level":
                return {"cmd": "STOCK_LEVEL", "arg": tail}
            return {"cmd": "UNKNOWN"}

    # Safe no-slash aliases (case-insensitive).
    # We intentionally do not alias plain "in" to avoid accidental triggers in normal chat.
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()
    arg_text = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "help":
        return {"cmd": "HELP"}
    if cmd == "menu":
        return {"cmd": "MENU"}
    if cmd == "out":
        return {"cmd": "OUT", "name": arg_text}
    if cmd == "restock":
        return {"cmd": "IN", "name": arg_text}
    if cmd == "confirm":
        return {"cmd": "CONFIRM", "target": arg_text}
    if cmd == "add":
        if "|" in arg_text:
            fields = [field.strip() for field in arg_text.split("|")]
            if len(fields) >= 2:
                return {
                    "cmd": "ADD",
                    "name": fields[0],
                    "price": fields[1],
                    "stock_qty": fields[2] if len(fields) > 2 else "",
                    "reorder_level": fields[3] if len(fields) > 3 else "",
                }
        match = re.match(r"(.+)\s+([0-9]+(?:\.[0-9]+)?)$", arg_text)
        if match:
            return {"cmd": "ADD", "name": match.group(1).strip(), "price": match.group(2).strip()}
        return {"cmd": "ADD", "name": "", "price": ""}
    if cmd == "stock":
        if not arg_text:
            return {"cmd": "STOCK_SNAPSHOT"}
        parts = arg_text.split(maxsplit=1)
        action = parts[0].lower()
        tail = parts[1].strip() if len(parts) > 1 else ""
        if action == "add":
            return {"cmd": "STOCK_ADD", "arg": tail}
        if action == "use":
            return {"cmd": "STOCK_USE", "arg": tail}
        if action == "set":
            return {"cmd": "STOCK_SET", "arg": tail}
        if action == "waste":
            return {"cmd": "STOCK_WASTE", "arg": tail}
        if action == "level":
            return {"cmd": "STOCK_LEVEL", "arg": tail}
        return {"cmd": "UNKNOWN"}

    return None


def process_owner_command(
    command: dict,
    db: Session,
    actor_platform: str = "owner",
    actor_id: str = "owner",
):
    cmd = command.get("cmd")

    if cmd == "CONFIRM":
        target = (command.get("target") or "").strip()
        if not target:
            return "Usage: /confirm <order_id>\n\n" + OWNER_HELP_TEXT

        if target.isdigit():
            order = db.query(Order).filter(Order.id == int(target), Order.status == "Pending").first()
            if order:
                ok, note, low_alerts = apply_sale_stock_deduction(db, order, actor_platform, actor_id)
                if not ok:
                    return note
                order.status = "PAID"
                db.commit()
                target_user = db.query(User).filter(User.id == order.user_id).first()
                if not target_user:
                    return f"Order #{order.id} marked PAID, but user record is missing."
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"Order #{order.id} confirmed. We are packing it now.", db)
                extras = []
                if note:
                    extras.append(note)
                if low_alerts:
                    extras.append("Low stock alerts:\n" + "\n".join([f"- {x}" for x in low_alerts]))
                extra_text = ("\n\n" + "\n\n".join(extras)) if extras else ""
                return f"Approved order #{order.id}.{extra_text}"
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
                ok, note, low_alerts = apply_sale_stock_deduction(db, order, actor_platform, actor_id)
                if not ok:
                    return note
                order.status = "PAID"
                db.commit()
                last_msg = db.query(Message).filter(Message.contact_id == target_user.phone_number).order_by(Message.id.desc()).first()
                platform = last_msg.platform if last_msg else "whatsapp"
                send_reply(platform, target_user.phone_number, f"Order #{order.id} confirmed. We are packing it now.", db)
                extras = []
                if note:
                    extras.append(note)
                if low_alerts:
                    extras.append("Low stock alerts:\n" + "\n".join([f"- {x}" for x in low_alerts]))
                extra_text = ("\n\n" + "\n\n".join(extras)) if extras else ""
                return f"Approved order #{order.id} for {target_user.name}.{extra_text}"
            return f"No pending order for {target_user.name}."
        return f"No user found for '{target}'."

    if cmd == "ADD":
        name = (command.get("name") or "").strip()
        price_raw = (command.get("price") or "").strip()
        if not name or not price_raw:
            return "Usage: /add <item name> | <price> [| <opening_stock> [| <reorder_level>]]"
        try:
            price = parse_naira_amount(price_raw)
            stock_raw = (command.get("stock_qty") or "").strip()
            level_raw = (command.get("reorder_level") or "").strip()
            stock_qty = parse_non_negative_int(stock_raw) if stock_raw else None
            reorder_level = parse_non_negative_int(level_raw) if level_raw else None
            item = db.query(MenuItem).filter(MenuItem.name.ilike(name)).first()
            if item:
                item.price = price
                item.is_available = True
                if stock_qty is not None:
                    item.stock_qty = stock_qty
                    if stock_qty == 0:
                        item.is_available = False
                if reorder_level is not None:
                    item.reorder_level = reorder_level
                action = "Updated"
            else:
                db.add(
                    MenuItem(
                        name=name,
                        price=price,
                        is_available=(stock_qty is None or stock_qty > 0),
                        stock_qty=stock_qty,
                        reorder_level=reorder_level if reorder_level is not None else 5,
                    )
                )
                action = "Added"
            db.commit()
            details = [f"{action} '{name}' @ N{price}."]
            target_item = db.query(MenuItem).filter(MenuItem.name.ilike(name)).first()
            if target_item and target_item.stock_qty is not None:
                details.append(f"Stock: {target_item.stock_qty}")
            if target_item and target_item.reorder_level is not None:
                details.append(f"Reorder level: {target_item.reorder_level}")
            return " ".join(details)
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

    if cmd == "STOCK_SNAPSHOT":
        items = db.query(MenuItem).all()
        return format_stock_snapshot(items)

    if cmd in {"STOCK_ADD", "STOCK_USE", "STOCK_SET", "STOCK_LEVEL"}:
        parsed = parse_name_qty((command.get("arg") or "").strip())
        if not parsed:
            return "Usage: /stock <add|use|set|level> <item> | <qty>"
        item_name, qty_raw = parsed
        try:
            qty = parse_non_negative_int(qty_raw)
            if cmd in {"STOCK_ADD", "STOCK_USE"} and qty == 0:
                return "Qty must be greater than 0."
            item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{item_name}%")).first()
            if not item:
                return f"Item '{item_name}' not found."

            if cmd == "STOCK_LEVEL":
                item.reorder_level = qty
                db.commit()
                return f"Reorder level for '{item.name}' set to {qty}."

            if item.stock_qty is None:
                item.stock_qty = 0

            if cmd == "STOCK_ADD":
                item.stock_qty += qty
                if item.stock_qty > 0:
                    item.is_available = True
                record_stock_movement(db, item, "add", qty, actor_platform, actor_id)
            elif cmd == "STOCK_USE":
                if item.stock_qty < qty:
                    return f"Insufficient stock for '{item.name}'. Have {item.stock_qty}, need {qty}."
                item.stock_qty -= qty
                if item.stock_qty <= 0:
                    item.stock_qty = 0
                    item.is_available = False
                record_stock_movement(db, item, "use", qty, actor_platform, actor_id)
            elif cmd == "STOCK_SET":
                item.stock_qty = qty
                item.is_available = qty > 0
                record_stock_movement(db, item, "set", qty, actor_platform, actor_id)

            low_alert = low_stock_message(item)
            db.commit()
            msg = f"Stock updated for '{item.name}': {item.stock_qty}"
            if low_alert:
                msg += f"\nLOW STOCK: {low_alert}"
            return msg
        except ValueError:
            return "Qty must be a whole number."

    if cmd == "STOCK_WASTE":
        parsed = parse_name_qty_reason((command.get("arg") or "").strip())
        if not parsed:
            return "Usage: /stock waste <item> | <qty> | <reason>"
        item_name, qty_raw, reason = parsed
        try:
            qty = parse_non_negative_int(qty_raw)
            if qty <= 0:
                return "Qty must be greater than 0."
            item = db.query(MenuItem).filter(MenuItem.name.ilike(f"%{item_name}%")).first()
            if not item:
                return f"Item '{item_name}' not found."
            if item.stock_qty is None:
                return f"Stock is untracked for '{item.name}'. Use /stock set first."
            if item.stock_qty < qty:
                return f"Insufficient stock for '{item.name}'. Have {item.stock_qty}, need {qty}."

            item.stock_qty -= qty
            if item.stock_qty <= 0:
                item.stock_qty = 0
                item.is_available = False
            record_stock_movement(db, item, "waste", qty, actor_platform, actor_id, reason=reason)
            low_alert = low_stock_message(item)
            db.commit()
            msg = f"Waste logged for '{item.name}': qty={qty}, reason={reason}. Stock now {item.stock_qty}."
            if low_alert:
                msg += f"\nLOW STOCK: {low_alert}"
            return msg
        except ValueError:
            return "Qty must be a whole number."

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
        reply = process_owner_command(owner_cmd, db, actor_platform=platform, actor_id=str(user_id))
        send_reply(platform, user_id, reply, db)
        return True
    if is_owner and not owner_cmd:
        send_reply(platform, user_id, "Use /help for vendor commands.", db)
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
    waiting_for_account_name = awaiting_payment_name_input(db, platform, user_id)
    if (
        not is_owner
        and pending_order
        and waiting_for_account_name
        and len(words) < 5
        and "CONFIRM" not in message_text.upper()
    ):
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

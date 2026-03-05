# Bukka AI Architecture Flow (LLM Extraction + Deterministic Pricing)

This system uses a strict split of responsibility:

- LLM responsibility: understand natural language and extract entities only.
- Backend responsibility: all business logic, pricing, totals, order persistence, and payment workflow.

## Why this split matters

LLMs are probabilistic. Arithmetic and rule enforcement should not be.

- Better accuracy: totals always come from the database (`menu_items` table), not model guesses.
- Better safety: pricing rules are auditable and version-controlled in Python.
- Easier debugging: if totals are wrong, investigate deterministic code, not prompt behavior.

## Request flow

1. Webhook receives user text (`/telegram/webhook` or `/webhook` for WhatsApp).
2. `process_message()` stores inbound message in `messages`.
3. LLM extraction chain runs with strict JSON contract:
   - `intent`
   - `items[]`
   - `qty[]`
4. Backend resolves extracted item names against `menu_items` (fuzzy matching + normalization).
5. Backend computes line totals and final total deterministically.
6. Backend writes/updates `orders` with computed values.
7. Backend returns operational reply (order summary, total, payment instruction).
8. Payment confirmation path remains deterministic (`PAID` -> owner confirmation -> status update).

## JSON contract from LLM

The LLM output is expected to be JSON only:

```json
{
  "intent": "order",
  "items": ["jollof", "beef"],
  "qty": [2, 1]
}
```

Notes:

- Arrays are index-aligned (`items[i]` uses `qty[i]`).
- Missing qty defaults to `1` in backend logic.
- Unknown items are ignored and reported back to user.
- No total is accepted from LLM.

## Deterministic backend logic

In `chat_manager.py`, deterministic functions now handle:

- `resolve_menu_item()` -> maps extracted item text to actual menu row.
- `build_order_from_extraction()` -> builds line items and computes total.
- `format_line_items()` -> generates canonical order summary string.

This guarantees total calculation uses current DB prices only.

## Data model touchpoints

- `menu_items`: source of truth for names, prices, availability.
- `orders`: persisted item summary and computed total.
- `messages`: conversation and outbound reply audit trail.

## Operational behavior by intent

- `order`: create/update pending order and return computed total.
- `inquiry`: return prices from menu table.
- `payment`: request bank-account-name confirmation path.
- `chitchat/unknown`: return safe deterministic guidance and live menu.

## Phase 2 Security Hardening

Implemented backend protections (with hardcoded secrets for now):

1. WhatsApp request signature verification:
   - Validates `x-hub-signature-256` using HMAC-SHA256 before payload processing.
2. Telegram webhook secret-token verification:
   - Validates `x-telegram-bot-api-secret-token` header before processing updates.
3. Demo reset protection:
   - `/demo/reset` now requires `x-admin-reset-token`.
4. CORS tightened:
   - Replaced wildcard origins with explicit local dev origins.

Current hardcoded placeholders to replace manually:

- `WHATSAPP_APP_SECRET` in `app/api/endpoints/whatsapp.py`
- `TELEGRAM_WEBHOOK_SECRET` in `app/api/endpoints/telegram.py`
- `DEMO_RESET_ADMIN_TOKEN` in `app/api/endpoints/demo.py`

## Phase 3 Reliability Hardening

Implemented reliability controls:

1. Webhook idempotency (DB-backed):
   - Added `processed_webhook_events` table with unique key on (`platform`, `external_event_id`).
   - Telegram/WhatsApp endpoints now claim event IDs before processing and ignore duplicates.
2. Retry-safe failure handling:
   - If processing fails after claim, claim is released so provider retries can succeed.
3. Better observability:
   - Replaced `print()` with structured logging in core processing paths.
4. More deterministic inbound ordering:
   - `process_message()` now accepts source webhook timestamp and stores it when available.

Implementation files:

- `app/models/sql_models.py` (new `ProcessedWebhookEvent` model)
- `alembic/versions/8e5c1d2a9f44_add_processed_webhook_events_table.py` (migration)
- `app/services/webhook_dedupe.py` (claim/release helper)
- `app/api/endpoints/whatsapp.py` and `app/api/endpoints/telegram.py` (idempotent webhook flow)
- `app/services/chat_manager.py` (processing success/failure return + logging + source timestamp)

## Phase 4 Data Integrity (Money)

Implemented money precision hardening:

1. Removed floating-point money from core models:
   - `menu_items.price` -> `INTEGER`
   - `orders.total_price` -> `INTEGER`
2. Added migration to convert existing DB values:
   - `f4b2c8d91a7e_convert_money_columns_to_integer.py`
3. Enforced deterministic integer math in service logic:
   - line totals and order totals are now integer naira
   - owner `ADD` command price parsing uses decimal-safe rounding to integer naira

Result:

- No floating-point drift in totals.
- Consistent pricing from database to response.

## Vendor Command UX (Improved)

The vendor command parser is now explicit to prevent accidental triggers.

Preferred commands:

- `/menu`
- `/add <item name> | <price>`
- `/out <item name>`
- `/in <item name>`
- `/confirm <order_id>`
- `/help`

Examples:

- `/add Jollof Rice | 500`
- `/out Chicken`
- `/confirm 105`

Notes:

- Commands are processed only for the configured owner account.
- Plain lowercase chat (e.g., `in stock?`) is no longer treated as a command.
- Legacy uppercase commands are still supported for compatibility (`ADD`, `IN`, `OUT`, `MENU`, `CONFIRM`).

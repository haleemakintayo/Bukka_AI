import hashlib
import json
import logging
import re
import time

from app.core.config import settings
from app.core.redis_client import get_redis_client


logger = logging.getLogger(__name__)

CACHE_PREFIX = "bukka:prompt_cache:v1"
CACHEABLE_INTENTS = {"greeting", "inquiry", "irrelevant"}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "for",
    "i",
    "is",
    "me",
    "my",
    "of",
    "on",
    "please",
    "the",
    "to",
    "we",
    "you",
    "your",
}
TRANSACTION_KEYWORDS = {
    "add",
    "buy",
    "checkout",
    "confirm",
    "done",
    "order",
    "paid",
    "pay",
    "remove",
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_prompt_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def tokenise_prompt(normalized_text: str) -> set[str]:
    tokens = {token for token in normalized_text.split() if token and token not in STOPWORDS}
    return tokens


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_likely_transactional_text(message_text: str) -> bool:
    normalized = normalize_prompt_text(message_text)
    tokens = set(normalized.split())
    if tokens & TRANSACTION_KEYWORDS:
        return True
    if re.search(r"\b\d+\b", normalized):
        return True
    return False


def is_cacheable_intent(intent: str) -> bool:
    return str(intent or "").strip().lower() in CACHEABLE_INTENTS


def build_context_fingerprint(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
) -> str:
    normalized_prompt = normalize_prompt_text(message_text)
    payload = {
        "platform": str(platform),
        "user_id": str(user_id),
        "role": str(role),
        "prompt_hash": _sha256(normalized_prompt),
        "menu_hash": _sha256(menu_text or ""),
        "model": str(model_identifier or "unknown"),
    }
    return _sha256(json.dumps(payload, sort_keys=True))


def _build_context_parts(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
) -> dict:
    normalized_prompt = normalize_prompt_text(message_text)
    return {
        "platform": str(platform),
        "user_id": str(user_id),
        "role": str(role),
        "normalized_prompt": normalized_prompt,
        "prompt_hash": _sha256(normalized_prompt),
        "menu_hash": _sha256(menu_text or ""),
        "model": str(model_identifier or "unknown"),
    }


def _exact_key(fingerprint: str) -> str:
    return f"{CACHE_PREFIX}:exact:{fingerprint}"


def _semantic_index_key(platform: str, user_id: str, role: str) -> str:
    return f"{CACHE_PREFIX}:semantic:index:{platform}:{user_id}:{role}"


def _semantic_entry_key(platform: str, user_id: str, role: str, signature: str) -> str:
    return f"{CACHE_PREFIX}:semantic:entry:{platform}:{user_id}:{role}:{signature}"


def _safe_json_loads(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_exact_cached_reply(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
) -> dict | None:
    if not settings.CACHE_ENABLED:
        return None

    client = get_redis_client()
    if client is None:
        return None

    fingerprint = build_context_fingerprint(
        platform=platform,
        user_id=user_id,
        role=role,
        message_text=message_text,
        menu_text=menu_text,
        model_identifier=model_identifier,
    )
    key = _exact_key(fingerprint)

    try:
        cached = _safe_json_loads(client.get(key))
        if not cached:
            return None
        if not is_cacheable_intent(cached.get("intent")):
            return None
        return cached
    except Exception:
        logger.exception("cache_error exact lookup failed")
        return None


def get_semantic_cached_reply(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
) -> dict | None:
    if not settings.CACHE_ENABLED or settings.CACHE_SEMANTIC_TTL_SEC <= 0:
        return None

    client = get_redis_client()
    if client is None:
        return None

    parts = _build_context_parts(
        platform=platform,
        user_id=user_id,
        role=role,
        message_text=message_text,
        menu_text=menu_text,
        model_identifier=model_identifier,
    )
    incoming_tokens = tokenise_prompt(parts["normalized_prompt"])
    if not incoming_tokens:
        return None

    index_key = _semantic_index_key(parts["platform"], parts["user_id"], parts["role"])
    now_ms = int(time.time() * 1000)
    min_ts = now_ms - max(settings.CACHE_SEMANTIC_TTL_SEC, settings.CACHE_COOLDOWN_SEC) * 1000

    try:
        # Keep the candidate set small and fresh.
        client.zremrangebyscore(index_key, 0, min_ts)
        signatures = client.zrevrange(index_key, 0, max(settings.CACHE_MAX_CANDIDATES - 1, 0))
    except Exception:
        logger.exception("cache_error semantic index lookup failed")
        return None

    best_match = None
    best_score = 0.0

    for signature in signatures:
        entry_key = _semantic_entry_key(parts["platform"], parts["user_id"], parts["role"], signature)
        try:
            entry = _safe_json_loads(client.get(entry_key))
        except Exception:
            logger.exception("cache_error semantic entry lookup failed")
            return None
        if not entry:
            continue
        if not is_cacheable_intent(entry.get("intent")):
            continue
        if entry.get("menu_hash") != parts["menu_hash"]:
            continue
        if entry.get("model") != parts["model"]:
            continue

        candidate_tokens = set(entry.get("tokens") or [])
        score = jaccard_similarity(incoming_tokens, candidate_tokens)
        if score >= settings.CACHE_SIMILARITY_THRESHOLD and score > best_score:
            best_match = entry
            best_score = score

    if not best_match:
        return None

    best_match["similarity_score"] = round(best_score, 4)
    return best_match


def record_recent_prompt_signature(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
    reply_text: str,
    intent: str,
) -> None:
    if not settings.CACHE_ENABLED or settings.CACHE_SEMANTIC_TTL_SEC <= 0:
        return
    if not is_cacheable_intent(intent):
        return

    client = get_redis_client()
    if client is None:
        return

    parts = _build_context_parts(
        platform=platform,
        user_id=user_id,
        role=role,
        message_text=message_text,
        menu_text=menu_text,
        model_identifier=model_identifier,
    )
    tokens = sorted(tokenise_prompt(parts["normalized_prompt"]))
    if not tokens:
        return

    now_ms = int(time.time() * 1000)
    signature = _sha256(
        f"{parts['platform']}|{parts['user_id']}|{parts['role']}|{parts['normalized_prompt']}"
    )
    index_key = _semantic_index_key(parts["platform"], parts["user_id"], parts["role"])
    entry_key = _semantic_entry_key(parts["platform"], parts["user_id"], parts["role"], signature)
    payload = {
        "reply": reply_text,
        "intent": str(intent).lower(),
        "tokens": tokens,
        "menu_hash": parts["menu_hash"],
        "model": parts["model"],
        "ts_ms": now_ms,
    }

    try:
        ttl = max(settings.CACHE_SEMANTIC_TTL_SEC, settings.CACHE_COOLDOWN_SEC)
        client.set(entry_key, json.dumps(payload), ex=max(ttl, 1))
        client.zadd(index_key, {signature: now_ms})
        client.expire(index_key, max(ttl, 1))
    except Exception:
        logger.exception("cache_error semantic signature update failed")


def store_cached_reply(
    platform: str,
    user_id: str,
    role: str,
    message_text: str,
    menu_text: str,
    model_identifier: str,
    intent: str,
    reply_text: str,
) -> bool:
    if not settings.CACHE_ENABLED or settings.CACHE_EXACT_TTL_SEC <= 0:
        return False
    if not is_cacheable_intent(intent):
        return False

    client = get_redis_client()
    if client is None:
        return False

    parts = _build_context_parts(
        platform=platform,
        user_id=user_id,
        role=role,
        message_text=message_text,
        menu_text=menu_text,
        model_identifier=model_identifier,
    )
    fingerprint = build_context_fingerprint(
        platform=platform,
        user_id=user_id,
        role=role,
        message_text=message_text,
        menu_text=menu_text,
        model_identifier=model_identifier,
    )
    payload = {
        "reply": reply_text,
        "intent": str(intent).lower(),
        "fingerprint": fingerprint,
        "menu_hash": parts["menu_hash"],
        "model": parts["model"],
        "ts_ms": int(time.time() * 1000),
    }

    try:
        client.set(_exact_key(fingerprint), json.dumps(payload), ex=max(settings.CACHE_EXACT_TTL_SEC, 1))
        record_recent_prompt_signature(
            platform=platform,
            user_id=user_id,
            role=role,
            message_text=message_text,
            menu_text=menu_text,
            model_identifier=model_identifier,
            reply_text=reply_text,
            intent=intent,
        )
        return True
    except Exception:
        logger.exception("cache_error exact store failed")
        return False

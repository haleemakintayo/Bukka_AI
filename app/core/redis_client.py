import logging
import time
from threading import Lock
from typing import Any

from app.core.config import settings

try:
    import redis
except Exception:  # pragma: no cover - keeps app fail-open before dependency install
    redis = None


logger = logging.getLogger(__name__)

_client: Any | None = None
_client_lock = Lock()
_last_error_log_ms = 0


def _log_client_error_once(message: str) -> None:
    global _last_error_log_ms
    now_ms = int(time.time() * 1000)
    if now_ms - _last_error_log_ms >= 60_000:
        logger.exception(message)
        _last_error_log_ms = now_ms


def get_redis_client() -> Any | None:
    global _client

    if not settings.CACHE_ENABLED:
        return None
    if not settings.REDIS_URL:
        return None
    if redis is None:
        return None
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client
        try:
            candidate = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
                health_check_interval=30,
            )
            candidate.ping()
            _client = candidate
        except Exception:
            _log_client_error_once("cache_error redis client init failed")
            _client = None

    return _client

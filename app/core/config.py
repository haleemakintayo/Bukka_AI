import logging
import os

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Using default=%s", name, raw, default)
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r. Using default=%s", name, raw, default)
        return default


class Settings:
    PROJECT_NAME: str = "Bukka AI CRM"

    # API Keys
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY")
    SERPAPI_API_KEY: str = os.getenv("SERPAPI_API_KEY")

    # Meta / WhatsApp Keys
    META_API_TOKEN: str = os.getenv("META_API_TOKEN")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID")
    OWNER_PHONE: str = os.getenv("OWNER_PHONE")

    DATABASE_URL: str = os.getenv("DATABASE_URL")

    # Redis / Prompt Cache
    REDIS_URL: str | None = os.getenv("REDIS_URL")
    CACHE_ENABLED: bool = _get_bool("CACHE_ENABLED", True)
    CACHE_EXACT_TTL_SEC: int = _get_int("CACHE_EXACT_TTL_SEC", 300)
    CACHE_SEMANTIC_TTL_SEC: int = _get_int("CACHE_SEMANTIC_TTL_SEC", 180)
    CACHE_COOLDOWN_SEC: int = _get_int("CACHE_COOLDOWN_SEC", 15)
    CACHE_SIMILARITY_THRESHOLD: float = _get_float("CACHE_SIMILARITY_THRESHOLD", 0.8)
    CACHE_MAX_CANDIDATES: int = _get_int("CACHE_MAX_CANDIDATES", 20)

    MENU = {
        "jollof_rice": 500,
        "fried_rice": 500,
        "chicken": 1000,
        "beef": 200,
        "plantain": 100,
        "water": 100,
        "soda": 250,
    }


settings = Settings()

if not settings.DATABASE_URL:
    logger.warning("DATABASE_URL not found. Using SQLite for local testing.")
    settings.DATABASE_URL = "sqlite:///./local_test.db"

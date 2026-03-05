import logging
import os

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


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

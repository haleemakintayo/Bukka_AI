import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "Bukka AI CRM"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY")
    SERPAPI_API_KEY: str = os.getenv("SERPAPI_API_KEY")
    
    MENU = {
        "jollof_rice": 500,
        "fried_rice": 500,
        "chicken": 1000,
        "beef": 200,
        "plantain": 100,
        "water": 100,
        "soda": 250
    }

settings = Settings()

if not settings.GROQ_API_KEY:
    raise ValueError("Error: GROQ_API_KEY missing in .env")
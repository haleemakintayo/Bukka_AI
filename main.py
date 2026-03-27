# main.py
import uvicorn
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.endpoints import telegram, whatsapp, demo, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Bukka AI - Powered by Llama & Groq",
    version="1.0"
)

# Mount the static directory to serve files like QR codes
app.mount("/static", StaticFiles(directory="static"), name="static")

# Tightened for backend safety. Add deployed frontend domain(s) explicitly.
ALLOWED_ORIGINS = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include the separated routers
app.include_router(telegram.router, prefix="/telegram", tags=["Telegram"])
app.include_router(whatsapp.router, tags=["WhatsApp"]) 
app.include_router(demo.router, prefix="/demo", tags=["Demo"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/")
def read_root():
    return {"status": "Bukka AI System Online 🚀"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

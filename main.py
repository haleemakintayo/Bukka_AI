# main.py
import uvicorn
from fastapi import FastAPI
from app.api.old_routes import router as api_router
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.endpoints import telegram, whatsapp, demo

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Bukka AI - Powered by Llama & Groq",
    version="1.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows ALL origins (Safe for a Hackathon demo)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# Include the separated routers
app.include_router(telegram.router, prefix="/telegram", tags=["Telegram"])
app.include_router(whatsapp.router, tags=["WhatsApp"]) 
app.include_router(demo.router, prefix="/demo", tags=["Demo"])


@app.get("/")
def read_root():
    return {"status": "Bukka AI System Online 🚀"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
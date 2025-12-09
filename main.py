# main.py
import uvicorn
from fastapi import FastAPI
from app.api.routes import router as api_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Bukka AI - Powered by Llama 3 & Groq",
    version="1.0"
)

# Include the routes from the API folder
app.include_router(api_router)

@app.get("/")
def health_check():
    return {"status": "online", "system": "Bukka AI"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
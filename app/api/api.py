from fastapi import APIRouter

# It's conventional to have an 'endpoints' module collecting the routers.
# We are assuming admin.py was moved to app/api/endpoints/admin.py and
# that demo.py and telegram.py exist there as well.
from app.api.endpoints import admin, demo, telegram, whatsapp

api_router = APIRouter()

v1_router = APIRouter()

v1_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
v1_router.include_router(demo.router, prefix="/demo", tags=["Demo"])
v1_router.include_router(telegram.router, prefix="/telegram", tags=["Telegram"])
v1_router.include_router(whatsapp.router, tags=["WhatsApp"]) # Included at the root of v1

api_router.include_router(v1_router, prefix="/v1")
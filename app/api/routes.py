# app/api/routes.py
from fastapi import APIRouter, HTTPException
from app.models.schemas import WhatsAppMessage, ConsultantResponse
from app.services.llm_engine import order_chain, consultant_agent
from app.core.config import settings

router = APIRouter()

# In-Memory DB (Move to database.py in real app)
USER_DB = {}

@router.post("/chat")
async def chat_endpoint(payload: WhatsAppMessage):
    """Handles Student Orders via WhatsApp"""
    try:
        # Run AI Chain
        response_data = order_chain.invoke({
            "menu": str(settings.MENU),
            "user_input": payload.message
        })
        
        # Simple Logic to add 'Total Price' to response
        # (You can expand this logic here without cluttering the main file)
        
        return {
            "bot_reply": response_data.get('reply_message'),
            "action": response_data.get('intent')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/consult", response_model=ConsultantResponse)
async def consult_endpoint(payload: WhatsAppMessage):
    """Handles Vendor Business Questions using SerpApi"""
    try:
        advice = consultant_agent.run(
            f"You are a business consultant. User asks: {payload.message}"
        )
        return {"advice": advice, "source": "Real-time Web Data"}
    except Exception as e:
        return {"advice": "Could not fetch data.", "source": "Error"}
# app/models/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional


class WhatsAppMessage(BaseModel):
    user_id: str = Field(..., description="User's Phone Number")
    message: str
    user_name: Optional[str] = "Student"


class OrderItem(BaseModel):
    item_name: str
    quantity: int

class AIResponse(BaseModel):
    intent: str = Field(description="ORDER, INQUIRY, or CHITCHAT")
    order_items: List[OrderItem] = []
    reply_message: str

class ConsultantResponse(BaseModel):
    advice: str
    source: str

class UserResponse(BaseModel):
    id: int
    name: str
    loyalty_points: int
    
    # Pydantic V2 Config to read SQLAlchemy models
    model_config = {"from_attributes": True}    
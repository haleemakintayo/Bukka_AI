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

class TextObject(BaseModel):
    body: str

class MessageObject(BaseModel):
    from_: str = Field(..., alias="from")
    id: str
    timestamp: str
    text: TextObject
    type: str = "text"

class ContactProfile(BaseModel):
    name: str

class ContactObject(BaseModel):
    profile: ContactProfile
    wa_id: str

class ValueObject(BaseModel):
    messaging_product: str
    metadata: dict
    contacts: List[ContactObject]
    messages: List[MessageObject]

class ChangeObject(BaseModel):
    value: ValueObject
    field: str = "messages"

class EntryObject(BaseModel):
    id: str
    changes: List[ChangeObject]

class WhatsAppWebhookSchema(BaseModel):
    object: str = "whatsapp_business_account"
    entry: List[EntryObject]

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "object": "whatsapp_business_account",
                "entry": [{
                    "id": "123456789",
                    "changes": [{
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "1234", "phone_number_id": "1234"},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "2348012345678"}],
                            "messages": [{
                                "from": "2348012345678",
                                "id": "wamid.HBg...",
                                "timestamp": "17000000",
                                "text": {"body": "I want jollof rice"},
                                "type": "text"
                            }]
                        },
                        "field": "messages"
                    }]
                }]
            }
        }    
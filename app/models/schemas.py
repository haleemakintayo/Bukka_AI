# app/models/schemas.py
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal

# --- 1. AI Extraction Models (Synchronized with llm_engine.py) ---

class ExtractedItem(BaseModel):
    item: str = Field(description="The exact name of the menu item from the Bukka")
    quantity: int = Field(default=1, ge=1, description="The number of portions requested")
    action: Literal["add", "remove"] = Field(description="Either 'add' or 'remove'")

class OrderExtractionResponse(BaseModel):
    thought: str = Field(description="Brief internal reasoning about the user's intent")
    message: str = Field(description="Auntie Chioma's reply in Nigerian Pidgin")
    extracted_items: List[ExtractedItem] = Field(default_factory=list, description="List of food items to add/remove")
    intent: Literal["greeting", "inquiry", "ordering", "checkout", "irrelevant"] = Field(
        description="Must be one of: 'greeting', 'inquiry', 'ordering', 'checkout', 'irrelevant'"
    )


# --- 2. Standard Models ---

class ConsultantResponse(BaseModel):
    advice: str
    source: str

class UserResponse(BaseModel):
    id: int
    name: str
    loyalty_points: int
    
    # Pydantic V2 Config to read SQLAlchemy models
    model_config = ConfigDict(from_attributes=True)    


# --- 3. WhatsApp Webhook Schemas (Meta Validation) ---

class TextObject(BaseModel):
    body: str

class MessageObject(BaseModel):
    from_: str = Field(..., alias="from")
    id: str
    timestamp: str
    text: TextObject
    type: str = "text"
    
    # Ignore extra fields (like 'from_logical_id')
    model_config = ConfigDict(extra="ignore")

class ContactProfile(BaseModel):
    name: str

class ContactObject(BaseModel):
    profile: ContactProfile
    wa_id: str

class ValueObject(BaseModel):
    messaging_product: str
    metadata: dict
    
    # Make these Optional so Status Updates (Read/Delivered) don't crash the app
    contacts: Optional[List[ContactObject]] = None
    messages: Optional[List[MessageObject]] = None
    
    # Ignore extra fields (like 'statuses')
    model_config = ConfigDict(extra="ignore")

class ChangeObject(BaseModel):
    value: ValueObject
    field: str = "messages"

class EntryObject(BaseModel):
    id: str
    changes: List[ChangeObject]

class WhatsAppWebhookSchema(BaseModel):
    object: str = "whatsapp_business_account"
    entry: List[EntryObject]

    # Pydantic V2 replacement for class Config
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
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
    )

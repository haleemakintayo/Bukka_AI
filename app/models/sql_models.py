# app/models/sql_models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, BigInteger
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    items = Column(String)
    total_price = Column(Float)
    status = Column(String, default="Pending")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String) 
    contact_id = Column(String, index=True) 
    direction = Column(String) 
    body = Column(String) 
    timestamp = Column(BigInteger) 

# --- NEW: Dynamic Menu Table ---
class MenuItem(Base):
    __tablename__ = "menu_items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # Unique name prevents duplicates
    price = Column(Float)
    is_available = Column(Boolean, default=True) # Handles "Stock" (True=In Stock, False=Finished)
# app/models/sql_models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    # orders = relationship("Order", back_populates="user") # Optional

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    items = Column(String)
    total_price = Column(Float)
    status = Column(String, default="Pending") # Pending, Paid, Confirmed
    # user = relationship("User", back_populates="orders") # Optional

# --- NEW: Message Table for Chat History ---
class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String)       # 'whatsapp' or 'telegram'
    contact_id = Column(String, index=True)     # Phone Number or Chat ID
    direction = Column(String)      # 'inbound' or 'outbound'
    body = Column(String)           # The text
    timestamp = Column(BigInteger)  # Milliseconds (for sorting)
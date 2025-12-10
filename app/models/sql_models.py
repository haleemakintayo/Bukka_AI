# app/models/sql_models.py
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    name = Column(String)
    loyalty_points = Column(Integer, default=0)
    
    # Relationship to orders
    orders = relationship("Order", back_populates="owner")

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    total_price = Column(Integer)
    items_json = Column(String)  # Storing items as a JSON string for simplicity
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Link back to User
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="orders")
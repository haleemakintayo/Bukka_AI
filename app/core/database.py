# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Get the URL from .env (e.g., postgresql://user:pass@localhost/dbname)
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# Create the Engine (The connection to Postgres)
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Create a SessionLocal class (Each request gets its own session)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for our models to inherit from
Base = declarative_base()

# Dependency to get DB session in endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
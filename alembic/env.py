# alembic/env.py
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# --- CHANGE 1: Import your Settings and Models ---
# We need to add the parent directory to path so python can find 'app'
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import Base
from app.core.config import settings  # To get the real DB URL
from app.models.sql_models import User, Order, Message # Import ALL your models here!

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- CHANGE 2: Set the Target Metadata ---
# This tells Alembic "Look at my FastAPI models to see what tables to create"
target_metadata = Base.metadata

# --- CHANGE 3: Overwrite the Database URL ---
# This replaces the fake URL in alembic.ini with the Real one from your .env or Heroku
def get_url():
    url = settings.DATABASE_URL
    # Fix for Heroku: It sometimes returns 'postgres://', but SQLAlchemy needs 'postgresql://'
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url() # Use our helper function
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    
    # We overwrite the config's sqlalchemy.url with our real one
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
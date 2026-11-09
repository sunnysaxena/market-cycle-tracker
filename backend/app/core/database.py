import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Project directories
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load project root .env without overriding existing system variables
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE, override=False)

# SQLite development fallback
SQLITE_PATH = DATA_DIR / "market_cycle_dev.db"

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{SQLITE_PATH.as_posix()}"

# SQLAlchemy declarative base
class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


# Database-specific connection settings
connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Database engine
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    """Provide a database session to API requests."""
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
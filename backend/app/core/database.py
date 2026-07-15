import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.models.models import Base

# DB Path definition
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/database.db")

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["pool_size"] = int(os.environ.get("SQLITE_POOL_SIZE", "5"))
    _engine_kwargs["max_overflow"] = int(os.environ.get("SQLITE_MAX_OVERFLOW", "15"))
    _engine_kwargs["pool_timeout"] = int(os.environ.get("SQLITE_POOL_TIMEOUT", "60"))

# Enable WAL mode and foreign key support for SQLite
engine = create_engine(
    DATABASE_URL,
    **_engine_kwargs,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    from app.core.schema_migrate import ensure_sqlite_schema

    ensure_sqlite_schema()

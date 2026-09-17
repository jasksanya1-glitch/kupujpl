import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.models import Base

# DB Path definition
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/database.db")

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    # QueuePool + SQLite eventually deadlocks the whole site (pool timeout).
    # NullPool opens/closes per session so requests never wait on a full pool.
    _engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": int(os.environ.get("SQLITE_BUSY_TIMEOUT", "20")),
    }
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = int(os.environ.get("DB_POOL_RECYCLE", "1800"))

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
        cursor.execute("PRAGMA busy_timeout=20000")
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

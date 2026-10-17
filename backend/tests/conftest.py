"""Shared pytest fixtures for backend tests."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure app imports see a safe test environment before models load.
# Default PE V2 off for legacy suite, but never clobber an explicit profile
# (e.g. PRICE_ENGINE_V2=1 pytest -m pe_v2) or per-test monkeypatch set before import.
os.environ.setdefault("PRICE_ENGINE_V2", "0")
os.environ.setdefault("GAMES_BASE_URL", "https://kupujpl.pl/games")

from app.models.models import Base  # noqa: E402


@pytest.fixture()
def db() -> Session:
    """In-memory SQLite session with schema created for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

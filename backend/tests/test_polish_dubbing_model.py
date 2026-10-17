"""Regression: gry-z-polskim-dubbingiem must not 500 on missing ORM columns."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.game_catalog_filter import _polish_language_flags, apply_appdetails_metadata
from app.models.models import Base, Game


def test_game_model_exposes_polish_language_columns():
    assert hasattr(Game, "has_polish_audio")
    assert hasattr(Game, "has_polish_interface")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("games")}
    assert "has_polish_audio" in cols
    assert "has_polish_interface" in cols
    engine.dispose()


def test_dubbing_query_filters_without_attribute_error():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all(
            [
                Game(title="A", slug="a", has_polish_audio=True, has_polish_interface=True),
                Game(title="B", slug="b", has_polish_audio=False, has_polish_interface=True),
                Game(title="C", slug="c", has_polish_audio=None, has_polish_interface=None),
            ]
        )
        db.commit()
        rows = db.query(Game).filter(Game.has_polish_audio.is_(True)).all()
        assert [g.slug for g in rows] == ["a"]
    finally:
        db.close()
        engine.dispose()


def test_polish_language_flags_from_steam_html():
    html = (
        "English<strong>*</strong>, Polish<strong>*</strong>, German"
        "<br><strong>*</strong>languages with full audio support"
    )
    iface, audio = _polish_language_flags(html)
    assert iface is True
    assert audio is True
    iface2, audio2 = _polish_language_flags("English<strong>*</strong>, Polish, German")
    assert iface2 is True
    assert audio2 is False


def test_apply_appdetails_sets_polish_flags():
    game = Game(title="X", slug="x")
    apply_appdetails_metadata(
        game,
        {
            "type": "game",
            "is_free": False,
            "supported_languages": "Polish<strong>*</strong>, English",
        },
    )
    assert game.has_polish_interface is True
    assert game.has_polish_audio is True

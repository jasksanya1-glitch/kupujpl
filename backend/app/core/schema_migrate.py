"""SQLite schema patches (add columns without Alembic)."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.core.database import engine

logger = logging.getLogger("schema_migrate")


def ensure_sqlite_schema() -> None:
    if engine.dialect.name != "sqlite":
        return
    insp = inspect(engine)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "last_seen_at" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_seen_at DATETIME"))
        logger.info("Added users.last_seen_at column")

    user_patches = [
        ("reset_password_code", "VARCHAR(128)"),
        ("reset_password_created_at", "DATETIME"),
    ]
    for name, col_type in user_patches:
        if name not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {col_type}"))
            logger.info("Added users.%s column", name)
            cols.add(name)

    if not insp.has_table("games"):
        return
    game_cols = {c["name"] for c in insp.get_columns("games")}
    patches = [
        ("steam_review_score", "INTEGER"),
        ("steam_review_count", "INTEGER"),
        ("steam_review_positive_pct", "FLOAT"),
        ("steam_app_type", "VARCHAR(24)"),
        ("is_free", "BOOLEAN"),
        ("is_coming_soon", "BOOLEAN"),
        ("steam_recommendations", "INTEGER"),
        ("steam_enriched", "BOOLEAN DEFAULT 0"),
    ]
    for name, col_type in patches:
        if name not in game_cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE games ADD COLUMN {name} {col_type}"))
            logger.info("Added games.%s column", name)
            game_cols.add(name)

    if insp.has_table("offers"):
        offer_cols = {c["name"] for c in insp.get_columns("offers")}
        if "match_confidence" not in offer_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE offers ADD COLUMN match_confidence FLOAT"))
            logger.info("Added offers.match_confidence column")

    if insp.has_table("favorites"):
        fav_cols = {c["name"] for c in insp.get_columns("favorites")}
        fav_patches = [
            ("alert_enabled", "BOOLEAN DEFAULT 0"),
            ("target_price_pln", "FLOAT"),
            ("baseline_price_pln", "FLOAT"),
            ("last_notified_at", "DATETIME"),
        ]
        for name, col_type in fav_patches:
            if name not in fav_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE favorites ADD COLUMN {name} {col_type}"))
                logger.info("Added favorites.%s column", name)

    if insp.has_table("users"):
        user_cols = {c["name"] for c in insp.get_columns("users")}
        alert_patches = [
            ("email_alerts_enabled", "BOOLEAN DEFAULT 1"),
            ("telegram_chat_id", "VARCHAR(32)"),
            ("telegram_link_token", "VARCHAR(64)"),
        ]
        for name, col_type in alert_patches:
            if name not in user_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {col_type}"))
                logger.info("Added users.%s column", name)
                user_cols.add(name)
        oauth_patches = [
            ("auth_provider", "VARCHAR(16) DEFAULT 'local'"),
            ("google_sub", "VARCHAR(64)"),
        ]
        for name, col_type in oauth_patches:
            if name not in user_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {col_type}"))
                logger.info("Added users.%s column", name)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub "
                        "ON users (google_sub) WHERE google_sub IS NOT NULL"
                    )
                )
        except Exception:
            pass

    if insp.has_table("games"):
        game_cols = {c["name"] for c in insp.get_columns("games")}
        price_patches = [
            ("lowest_ever_pln", "FLOAT"),
            ("lowest_ever_at", "DATETIME"),
            ("avg_best_price_30d", "FLOAT"),
        ]
        for name, col_type in price_patches:
            if name not in game_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE games ADD COLUMN {name} {col_type}"))
                logger.info("Added games.%s column", name)

    if insp.has_table("site_visits"):
        visit_cols = {c["name"] for c in insp.get_columns("site_visits")}
        utm_patches = [
            ("utm_source", "VARCHAR(64)"),
            ("utm_medium", "VARCHAR(64)"),
            ("utm_campaign", "VARCHAR(128)"),
        ]
        for name, col_type in utm_patches:
            if name not in visit_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE site_visits ADD COLUMN {name} {col_type}"))
                logger.info("Added site_visits.%s column", name)
        if "client_agent" not in visit_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE site_visits ADD COLUMN client_agent VARCHAR(32)"))
            logger.info("Added site_visits.client_agent column")

    if insp.has_table("site_sessions"):
        session_cols = {c["name"] for c in insp.get_columns("site_sessions")}
        if "client_agent" not in session_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE site_sessions ADD COLUMN client_agent VARCHAR(32)"))
            logger.info("Added site_sessions.client_agent column")

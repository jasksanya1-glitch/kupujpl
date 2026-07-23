"""SQLite schema patches (add columns without Alembic)."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.core.database import engine

logger = logging.getLogger("schema_migrate")


def _ensure_offers_activation_region() -> None:
    """Add offers.activation_region for US/PL shopping filters (sqlite + postgres)."""
    insp = inspect(engine)
    if not insp.has_table("offers"):
        return
    offer_cols = {c["name"] for c in insp.get_columns("offers")}
    if "activation_region" in offer_cols:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    "ALTER TABLE offers ADD COLUMN activation_region VARCHAR(16) "
                    "NOT NULL DEFAULT 'unknown'"
                )
            )
        else:
            conn.execute(
                text(
                    "ALTER TABLE offers ADD COLUMN activation_region VARCHAR(16) "
                    "DEFAULT 'unknown'"
                )
            )
            conn.execute(
                text("UPDATE offers SET activation_region = 'unknown' WHERE activation_region IS NULL")
            )
            try:
                conn.execute(
                    text("ALTER TABLE offers ALTER COLUMN activation_region SET NOT NULL")
                )
            except Exception:
                pass
        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_offers_game_shop_region "
                    "ON offers (game_id, shop_name, activation_region)"
                )
            )
        except Exception:
            pass
        # Official / global-leaning shops: prefer global over unknown for display clarity
        conn.execute(
            text(
                "UPDATE offers SET activation_region = 'global' "
                "WHERE shop_name IN ('Steam', 'GOG', 'Epic Games', 'Fanatical', 'Humble Store') "
                "AND (activation_region IS NULL OR activation_region = 'unknown')"
            )
        )
        conn.execute(
            text(
                "UPDATE offers SET activation_region = 'na' "
                "WHERE shop_name = 'Steam US' "
                "AND (activation_region IS NULL OR activation_region = 'unknown')"
            )
        )
    logger.info("Added offers.activation_region column")


def ensure_sqlite_schema() -> None:
    _ensure_offers_activation_region()
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
            ("alert_shop_filter", "VARCHAR(16) DEFAULT 'any'"),
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
            ("utm_term", "VARCHAR(128)"),
            ("utm_content", "VARCHAR(128)"),
            ("gclid", "VARCHAR(128)"),
            ("wbraid", "VARCHAR(128)"),
            ("gbraid", "VARCHAR(128)"),
            ("referrer_host", "VARCHAR(120)"),
            ("referrer_url", "VARCHAR(700)"),
            ("user_agent", "VARCHAR(480)"),
            ("is_suspected_bot", "BOOLEAN DEFAULT 0"),
            ("bot_reason", "VARCHAR(64)"),
            ("is_verified_human", "BOOLEAN DEFAULT 0"),
            ("human_verification", "VARCHAR(32)"),
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
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_site_visits_is_suspected_bot "
                        "ON site_visits (is_suspected_bot)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_site_visits_bot_reason "
                        "ON site_visits (bot_reason)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_site_visits_referrer_host "
                        "ON site_visits (referrer_host)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_site_visits_is_verified_human "
                        "ON site_visits (is_verified_human)"
                    )
                )
        except Exception:
            pass

    if insp.has_table("site_sessions"):
        session_cols = {c["name"] for c in insp.get_columns("site_sessions")}
        if "client_agent" not in session_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE site_sessions ADD COLUMN client_agent VARCHAR(32)"))
            logger.info("Added site_sessions.client_agent column")

from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Index, Table
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

game_categories = Table(
    "game_categories",
    Base.metadata,
    Column("game_id", ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    kind = Column(String(20), nullable=False, default="genre")  # genre | feature
    steam_id = Column(String(32), nullable=True, index=True)
    game_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    games = relationship("Game", secondary=game_categories, back_populates="categories")


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    cover_image = Column(String(500), nullable=True)
    description = Column(String(2000), nullable=True)
    steam_appid = Column(Integer, nullable=True, unique=True, index=True)
    release_date = Column(String(50), nullable=True)
    rating = Column(Float, nullable=True)
    steam_review_score = Column(Integer, nullable=True)
    steam_review_count = Column(Integer, nullable=True)
    steam_review_positive_pct = Column(Float, nullable=True)
    steam_app_type = Column(String(24), nullable=True)
    is_free = Column(Boolean, default=False)
    is_coming_soon = Column(Boolean, default=False)
    steam_recommendations = Column(Integer, nullable=True)
    steam_enriched = Column(Boolean, default=False)
    lowest_ever_pln = Column(Float, nullable=True)
    lowest_ever_at = Column(DateTime, nullable=True)
    avg_best_price_30d = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    offers = relationship("Offer", back_populates="game", cascade="all, delete-orphan")
    price_snapshots = relationship("PriceSnapshot", back_populates="game", cascade="all, delete-orphan")
    categories = relationship("Category", secondary=game_categories, back_populates="games")

    def __repr__(self):
        return f"<Game(title='{self.title}', slug='{self.slug}')>"


class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    shop_name = Column(String(100), nullable=False)
    # eu | na | global | unknown — keyshop activation region for shopping-region filter
    activation_region = Column(String(16), nullable=False, default="unknown")
    price_pln = Column(Float, nullable=False)
    original_price_pln = Column(Float, nullable=True)
    affiliate_url = Column(String(1000), nullable=False)
    is_official = Column(Boolean, default=False)
    in_stock = Column(Boolean, default=True)
    match_confidence = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    game = relationship("Game", back_populates="offers")

    def __repr__(self):
        return f"<Offer(shop='{self.shop_name}', region={self.activation_region}, price={self.price_pln} PLN)>"


Index("idx_offers_price_official", Offer.game_id, Offer.is_official, Offer.price_pln)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    auth_provider = Column(String(16), nullable=False, default="local")
    google_sub = Column(String(64), nullable=True, unique=True, index=True)
    reset_password_code = Column(String(128), nullable=True, index=True)
    reset_password_created_at = Column(DateTime, nullable=True)
    email_alerts_enabled = Column(Boolean, default=True)
    telegram_chat_id = Column(String(32), nullable=True, index=True)
    telegram_link_token = Column(String(64), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    push_subscriptions = relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User(email='{self.email}')>"


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_enabled = Column(Boolean, default=False)
    target_price_pln = Column(Float, nullable=True)
    baseline_price_pln = Column(Float, nullable=True)
    # any | official | keyshop
    alert_shop_filter = Column(String(16), nullable=False, default="any")
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")
    game = relationship("Game")

    def __repr__(self):
        return f"<Favorite(user_id={self.user_id}, game_id={self.game_id})>"


Index("idx_user_game_favorite", Favorite.user_id, Favorite.game_id, unique=True)


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    shop_name = Column(String(100), nullable=False)
    price_pln = Column(Float, nullable=False)
    in_stock = Column(Boolean, default=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)

    game = relationship("Game", back_populates="price_snapshots")


Index("idx_price_snap_game_shop_time", PriceSnapshot.game_id, PriceSnapshot.shop_name, PriceSnapshot.recorded_at)
Index(
    "idx_offers_game_shop_region",
    Offer.game_id,
    Offer.shop_name,
    Offer.activation_region,
)


class SiteVisit(Base):
    __tablename__ = "site_visits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    visited_at = Column(DateTime, default=datetime.utcnow, index=True)
    path = Column(String(480), nullable=False, index=True)
    visitor_key = Column(String(32), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    utm_source = Column(String(64), nullable=True, index=True)
    utm_medium = Column(String(64), nullable=True)
    utm_campaign = Column(String(128), nullable=True)
    utm_term = Column(String(128), nullable=True)
    utm_content = Column(String(128), nullable=True)
    gclid = Column(String(128), nullable=True)
    wbraid = Column(String(128), nullable=True)
    gbraid = Column(String(128), nullable=True)
    referrer_host = Column(String(120), nullable=True, index=True)
    referrer_url = Column(String(700), nullable=True)
    geo_city = Column(String(120), nullable=True)
    geo_country = Column(String(120), nullable=True)
    geo_country_code = Column(String(8), nullable=True)
    client_agent = Column(String(32), nullable=True)
    user_agent = Column(String(480), nullable=True)
    is_suspected_bot = Column(Boolean, default=False, index=True)
    bot_reason = Column(String(64), nullable=True, index=True)

    user = relationship("User")


class SiteSession(Base):
    __tablename__ = "site_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    visitor_key = Column(String(32), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_active_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_path = Column(String(480), nullable=True)
    page_views = Column(Integer, default=0)
    geo_city = Column(String(120), nullable=True)
    geo_country = Column(String(120), nullable=True)
    client_agent = Column(String(32), nullable=True)

    user = relationship("User")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(512), nullable=False, unique=True, index=True)
    p256dh = Column(String(256), nullable=False)
    auth_key = Column(String(128), nullable=False)
    user_agent = Column(String(240), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="push_subscriptions")


class IpGeoCache(Base):
    __tablename__ = "ip_geo_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_hash = Column(String(32), nullable=False, unique=True, index=True)
    city = Column(String(120), nullable=True)
    country_code = Column(String(8), nullable=True)
    country_name = Column(String(120), nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clicked_at = Column(DateTime, default=datetime.utcnow, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id", ondelete="SET NULL"), nullable=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="SET NULL"), nullable=True, index=True)
    game_slug = Column(String(255), nullable=True, index=True)
    game_title = Column(String(255), nullable=True)
    shop_name = Column(String(100), nullable=False, index=True)
    price_pln = Column(Float, nullable=True)
    destination_host = Column(String(120), nullable=True)
    has_tracking = Column(Boolean, default=False)
    is_monetized = Column(Boolean, default=True)
    visitor_key = Column(String(32), nullable=False, index=True)

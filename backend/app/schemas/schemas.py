from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime
import re

class OfferBase(BaseModel):
    shop_name: str
    price_pln: float
    original_price_pln: Optional[float] = None
    affiliate_url: str
    is_official: bool
    in_stock: bool
    activation_region: Optional[str] = "unknown"

class OfferResponse(OfferBase):
    id: int
    game_id: int
    updated_at: datetime
    match_confidence: Optional[float] = None
    low_confidence: bool = False
    trust_label: Optional[str] = None
    trust_tier: Optional[str] = None
    trust_note: Optional[str] = None
    refund_policy_url: Optional[str] = None
    refund_note_pl: Optional[str] = None
    refund_note_uk: Optional[str] = None

    class Config:
        from_attributes = True


class GameBase(BaseModel):
    title: str
    slug: str
    cover_image: Optional[str] = None
    description: Optional[str] = None
    steam_appid: Optional[int] = None
    release_date: Optional[str] = None
    rating: Optional[float] = None

class GameCreate(GameBase):
    pass

class GameResponse(GameBase):
    id: int
    created_at: datetime
    offers: List[OfferResponse] = []
    offers_updated_at: Optional[datetime] = None
    offers_stale: bool = False
    in_stock_shop_count: int = 0
    in_tier_a_daily_scan: bool = False
    next_tier_a_scan_at: Optional[str] = None
    lowest_ever_pln: Optional[float] = None
    avg_best_price_30d: Optional[float] = None
    lowest_ever_label: Optional[str] = None
    at_historical_low: bool = False
    steam_price_pln: Optional[float] = None
    savings_pln: Optional[float] = None
    savings_pct: Optional[int] = None
    is_free: bool = False
    related_dlc: List["GameListResponse"] = []
    parent_game: Optional["GameListResponse"] = None

    class Config:
        from_attributes = True


class RefreshOffersResponse(BaseModel):
    queued: bool
    offers_updated_at: Optional[datetime] = None
    message: str


class GameListResponse(BaseModel):
    id: int
    title: str
    slug: str
    cover_image: Optional[str] = None
    steam_appid: Optional[int] = None
    release_date: Optional[str] = None
    rating: Optional[float] = None
    best_price_pln: Optional[float] = None
    best_price_is_official: Optional[bool] = None
    best_shop_name: Optional[str] = None
    steam_price_pln: Optional[float] = None
    savings_pln: Optional[float] = None
    savings_pct: Optional[int] = None
    lowest_ever_pln: Optional[float] = None
    avg_best_price_30d: Optional[float] = None
    lowest_ever_label: Optional[str] = None
    at_historical_low: bool = False
    deal_age_label: Optional[str] = None
    offers_updated_at: Optional[datetime] = None
    is_free: bool = False

    class Config:
        from_attributes = True


class UserRegister(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Nieprawidłowy adres e-mail")
        return v

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Hasło musi mieć co najmniej 8 znaków")
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str


class GoogleAuthConfigResponse(BaseModel):
    enabled: bool
    client_id: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Nieprawidłowy adres e-mail")
        return v


class ResetPasswordRequest(BaseModel):
    code: str
    password: str

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Hasło musi mieć co najmniej 8 znaków")
        return v


class MessageResponse(BaseModel):
    message: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Hasło musi mieć co najmniej 8 znaków")
        return v


class AccountSummaryResponse(BaseModel):
    email: str
    member_since: datetime
    last_seen_at: Optional[datetime] = None
    favorites_count: int
    favorites_with_price: int
    cheapest_price_pln: Optional[float] = None
    cheapest_game_title: Optional[str] = None
    email_alerts_enabled: bool = True


class UserResponse(BaseModel):
    id: int
    email: str
    created_at: datetime
    auth_provider: Optional[str] = "local"
    has_google: bool = False
    is_site_owner: bool = False

    class Config:
        from_attributes = True

    @classmethod
    def from_user(cls, user, *, is_site_owner: bool = False) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            created_at=user.created_at,
            auth_provider=getattr(user, "auth_provider", None) or "local",
            has_google=bool(getattr(user, "google_sub", None)),
            is_site_owner=is_site_owner,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class FavoriteGameResponse(GameListResponse):
    favorited_at: datetime
    alert_enabled: bool = False
    target_price_pln: Optional[float] = None
    baseline_price_pln: Optional[float] = None
    alert_shop_filter: str = "any"

    class Config:
        from_attributes = True


class FavoriteAlertUpdate(BaseModel):
    alert_enabled: bool
    target_price_pln: Optional[float] = None
    alert_shop_filter: Optional[str] = None  # any | official | keyshop


class PriceHistoryPoint(BaseModel):
    date: str
    best_price_pln: float


class PriceHistoryResponse(BaseModel):
    slug: str
    title: str
    lowest_ever_pln: Optional[float] = None
    avg_best_price_30d: Optional[float] = None
    at_historical_low: bool = False
    points: List[PriceHistoryPoint] = []


class TelegramLinkResponse(BaseModel):
    bot_username: str
    link_token: str
    start_command: str


class AccountAlertsUpdate(BaseModel):
    email_alerts_enabled: bool


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    expirationTime: Optional[int] = None


class PushUnsubscribeIn(BaseModel):
    endpoint: Optional[str] = None


class PushStatusResponse(BaseModel):
    supported: bool = True
    configured: bool = False
    subscribed: bool = False
    subscription_count: int = 0
    vapid_public_key: Optional[str] = None


class VapidPublicKeyResponse(BaseModel):
    configured: bool
    public_key: Optional[str] = None


class SteamWishlistImportRequest(BaseModel):
    profile: str


class SteamWishlistImportGameItem(BaseModel):
    game_id: Optional[int] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    steam_appid: Optional[int] = None
    message: Optional[str] = None
    reason: Optional[str] = None


class SteamWishlistImportResponse(BaseModel):
    ok: bool
    steam_id64: Optional[str] = None
    wishlist_total: int = 0
    processed: int = 0
    truncated: bool = False
    tier_a_appended: int = 0
    scan_notice_pl: Optional[str] = None
    schedule: dict[str, str] = {}
    message: Optional[str] = None
    tracked: List[SteamWishlistImportGameItem] = []
    already_tracked: List[SteamWishlistImportGameItem] = []
    added_to_catalog: List[SteamWishlistImportGameItem] = []
    queued_for_scan: List[SteamWishlistImportGameItem] = []
    skipped: List[SteamWishlistImportGameItem] = []


class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    kind: str
    game_count: int

    class Config:
        from_attributes = True


class GamesPageResponse(BaseModel):
    items: List[GameListResponse]
    total: int
    page: int
    pages: int
    limit: int


class HomeSectionResponse(BaseModel):
    slug: str
    catalog_slug: str = ""
    name: str
    subtitle: str
    games: List[GameListResponse]


class HomePageResponse(BaseModel):
    sections: List[HomeSectionResponse]
    spotlight: List[GameListResponse] = []
    new_deals: List[GameListResponse] = []
    historical_lows: List[GameListResponse] = []
    freebies: List[GameListResponse] = []
    updated_at: Optional[str] = None


class HomeCurationUpdateRequest(BaseModel):
    spotlight_slugs: List[str]


class HomeCurationImportRequest(BaseModel):
    url: str


class HomeCurationGameResponse(GameListResponse):
    in_stock_shop_count: int = 0


class HomeCurationResponse(BaseModel):
    spotlight_slugs: List[str]
    updated_at: Optional[str] = None
    games: List[HomeCurationGameResponse] = []


class TrackVisitRequest(BaseModel):
    path: str
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None
    gclid: Optional[str] = None
    wbraid: Optional[str] = None
    gbraid: Optional[str] = None
    referrer_url: Optional[str] = None
    client_agent: Optional[str] = None


class RemoteOfferItem(BaseModel):
    shop_name: str
    price_pln: float
    product_url: str
    is_official: bool = False
    match_confidence: Optional[float] = None


class RemoteOfferGameUpdate(BaseModel):
    game_id: int
    offers: List[RemoteOfferItem]


class RemoteOfferBulkRequest(BaseModel):
    updates: List[RemoteOfferGameUpdate]
    source: str = "local-pc"


GameResponse.model_rebuild()


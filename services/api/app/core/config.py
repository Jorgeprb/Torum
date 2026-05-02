from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    project_name: str = "Torum"
    environment: str = "local"
    tailscale_enabled: bool = False
    public_host: str = "localhost"
    api_v1_prefix: str = "/api/v1"

    database_url: str
    redis_url: str

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://100.124.49.118:4173,http://172.27.176.1:4173,http://172.18.64.1:4173,http://192.168.1.86:4173,https://pc-oficina.tail652fa7.ts.net"

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    initial_admin_username: str
    initial_admin_email: str
    initial_admin_password: SecretStr
    initial_trader_username: str
    initial_trader_email: str
    initial_trader_password: SecretStr

    trading_mode: Literal["PAPER", "DEMO", "LIVE"] = "PAPER"
    mt5_bridge_base_url: str | None = "http://host.docker.internal:9100"
    price_stale_after_seconds: int = 30
    candle_price_source: str = "BID"
    mock_market_tick_interval_seconds: float = 1.0
    live_trading_enabled: bool = False
    default_magic_number: int = 260426
    default_deviation_points: int = 20

    news_block_enabled: bool = False
    news_block_minutes_before: int = 60
    news_block_minutes_after: int = 60
    finnhub_calendar_url: str = "https://finnhub.io/api/v1/calendar/economic"
    finnhub_api_key: SecretStr = "d7p2inpr01qr68pbfq1gd7p2inpr01qr68pbfq20"
    news_provider_timeout_seconds: float = 10.0

    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:admin@torum.dev"

    watchdog_base_url: str | None = "http://host.docker.internal:9200"
    watchdog_admin_token: SecretStr | None = None
    watchdog_timeout_seconds: float = 5.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

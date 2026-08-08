from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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
    service_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TORUM_SERVICE_TOKEN", "SERVICE_TOKEN"),
    )
    internal_auth_required: bool = True
    mt5_missing_position_confirmations: int = 3
    mt5_order_request_timeout_seconds: float = 3.0
    strategy_run_on_candle_close_only: bool = True
    torum_reservation_ttl_seconds: int = 120
    torum_ambiguous_reservation_ttl_seconds: int = 86_400
    torum_reconciliation_grace_seconds: int = 20
    torum_reconciliation_absent_syncs: int = 3
    torum_max_entry_delay_seconds: float = 60.0
    strategy_symbol_lock_timeout_seconds: float = 1.0
    strategy_pipeline_warn_ms: float = 1000.0
    strategy_pipeline_hard_timeout_seconds: float = 4.0
    risk_recompute_debounce_seconds: float = 0.5
    risk_use_mt5_profit_calibration: bool = True
    risk_mt5_calibration_timeout_seconds: float = 2.0
    trade_job_poll_interval_seconds: float = 0.5
    trade_job_max_attempts: int = 8
    run_internal_schedulers: bool = True
    enforce_single_worker: bool = True

    # Persistent diagnostics. Docker mounts this directory to ./logs on the host.
    log_to_files: bool = True
    log_directory: str = "logs"
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 20
    strategy_trace_enabled: bool = True
    strategy_trace_recent_candles: int = 30
    price_stale_after_seconds: int = 30
    candle_price_source: str = "BID"
    chart_broker_time_zone: str = "Etc/GMT-3"
    mock_market_tick_interval_seconds: float = 1.0
    live_trading_enabled: bool = False
    default_magic_number: int = 260426
    default_deviation_points: int = 20

    news_block_enabled: bool = False
    news_block_minutes_before: int = 60
    news_block_minutes_after: int = 60
    finnhub_calendar_url: str = "https://finnhub.io/api/v1/calendar/economic"
    finnhub_api_key: SecretStr | None = None
    news_provider_timeout_seconds: float = 10.0

    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:admin@torum.dev"

    watchdog_base_url: str | None = "http://host.docker.internal:9200"
    watchdog_admin_token: SecretStr | None = None
    watchdog_timeout_seconds: float = 15.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

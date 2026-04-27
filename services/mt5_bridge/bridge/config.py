from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    torum_api_base_url: str = "http://127.0.0.1:8000"
    torum_ticks_batch_endpoint: str = "/api/ticks/batch"
    torum_health_endpoint: str = "/api/health"
    torum_symbols_endpoint: str = "/api/symbols"
    torum_mt5_status_endpoint: str = "/api/mt5/status"
    torum_http_timeout_seconds: float = 10.0
    torum_http_max_retries: int = 3

    mt5_poll_interval_ms: int = 250
    mt5_batch_max_size: int = 500
    mt5_batch_flush_interval_ms: int = 1000
    mt5_buffer_max_size: int = 50000
    mt5_lookback_seconds_on_start: int = 10
    mt5_copy_ticks_max_count: int = 10000
    mt5_enable_real_trading: bool = False
    mt5_allowed_account_modes: str = "DEMO"
    mt5_price_source: str = "auto"
    mt5_magic_number: int = 260426
    mt5_market_data_only: bool = True
    mt5_symbols: str = ""
    mt5_fallback_symbol_mappings: str = Field(
        default="XAUUSD:XAUUSD,XAUEUR:XAUEUR,XAUAUD:XAUAUD,XAUJPY:XAUJPY,DXY:DXY"
    )
    mt5_bridge_host: str = "127.0.0.1"
    mt5_bridge_port: int = 9100
    mt5_allow_order_execution: bool = False
    mt5_default_deviation_points: int = 20
    mt5_order_comment_prefix: str = "Torum"
    mt5_diagnostic_log_interval_seconds: int = 5

    log_level: str = "INFO"

    @property
    def api_base_url(self) -> str:
        return self.torum_api_base_url.rstrip("/")

    @property
    def allowed_account_modes(self) -> set[str]:
        return {mode.strip().upper() for mode in self.mt5_allowed_account_modes.split(",") if mode.strip()}

    @property
    def enabled_internal_symbols(self) -> set[str] | None:
        if not self.mt5_symbols.strip():
            return None
        return {symbol.strip().upper() for symbol in self.mt5_symbols.split(",") if symbol.strip()}


@lru_cache
def get_settings() -> BridgeSettings:
    return BridgeSettings()

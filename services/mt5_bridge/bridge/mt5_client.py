from datetime import UTC, datetime
import logging
from typing import Any

from bridge.account_state import AccountState, account_state_from_mt5
from bridge.config import BridgeSettings

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5_module
except ImportError:  # pragma: no cover - exercised only on machines without MT5 package
    mt5_module = None


class MT5ClientError(RuntimeError):
    pass


class MT5Client:
    def __init__(self, settings: BridgeSettings, mt5: Any | None = None) -> None:
        self.settings = settings
        self.mt5 = mt5 if mt5 is not None else mt5_module
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        if not self.mt5.initialize():
            raise MT5ClientError(f"MT5 initialize failed: {self.mt5.last_error()}")
        self._initialized = True
        logger.info("MT5 initialized")

    def shutdown(self) -> None:
        if self.mt5 is not None:
            self.mt5.shutdown()
            self._initialized = False
            logger.info("MT5 shutdown completed")

    def get_account_info(self) -> Any:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        account_info = self.mt5.account_info()
        if account_info is None:
            raise MT5ClientError(f"MT5 account_info failed: {self.mt5.last_error()}")
        return account_info

    def get_account_state(self) -> AccountState:
        return account_state_from_mt5(self.get_account_info())

    def get_terminal_info(self) -> Any:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        terminal_info = self.mt5.terminal_info()
        if terminal_info is None:
            raise MT5ClientError(f"MT5 terminal_info failed: {self.mt5.last_error()}")
        return terminal_info

    def is_connected(self) -> bool:
        try:
            terminal_info = self.get_terminal_info()
        except MT5ClientError:
            return False
        return bool(getattr(terminal_info, "connected", False))

    def select_symbol(self, broker_symbol: str) -> bool:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        selected = bool(self.mt5.symbol_select(broker_symbol, True))
        if not selected:
            logger.error("MT5 symbol_select failed for %s: %s", broker_symbol, self.mt5.last_error())
            return False
        info = self.mt5.symbol_info(broker_symbol)
        if info is None:
            logger.warning("MT5 symbol_info unavailable for %s after symbol_select", broker_symbol)
            return True
        logger.info(
            "MT5 symbol selected: broker_symbol=%s digits=%s point=%s trade_mode=%s visible=%s description=%s",
            broker_symbol,
            getattr(info, "digits", None),
            getattr(info, "point", None),
            getattr(info, "trade_mode", None),
            getattr(info, "visible", None),
            getattr(info, "description", None),
        )
        return selected

    def get_latest_tick(self, broker_symbol: str) -> Any | None:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            logger.debug("No latest tick for %s: %s", broker_symbol, self.mt5.last_error())
        return tick

    def get_ticks_since(self, broker_symbol: str, since_datetime: datetime) -> list[Any]:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
        since = _ensure_utc(since_datetime)
        until = datetime.now(UTC)
        flags = getattr(self.mt5, "COPY_TICKS_ALL", 0)

        ticks = self.mt5.copy_ticks_range(broker_symbol, since, until, flags)
        if ticks is None:
            logger.warning("copy_ticks_range failed for %s: %s", broker_symbol, self.mt5.last_error())
            ticks = self.mt5.copy_ticks_from(
                broker_symbol,
                since,
                self.settings.mt5_copy_ticks_max_count,
                flags,
            )
        if ticks is None:
            logger.warning("copy_ticks_from failed for %s: %s", broker_symbol, self.mt5.last_error())
            return []
        return list(ticks)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

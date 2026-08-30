from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Any, Iterator

from bridge.account_state import AccountState, account_state_from_mt5
from bridge.config import BridgeSettings
from bridge.mt5_access import AccessPriority, MT5AccessCoordinator

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5_module
except ImportError:  # pragma: no cover - exercised only on machines without MT5 package
    mt5_module = None


class MT5ClientError(RuntimeError):
    pass


class MT5Client:
    def __init__(
        self,
        settings: BridgeSettings,
        mt5: Any | None = None,
        coordinator: MT5AccessCoordinator | None = None,
    ) -> None:
        self.settings = settings
        self.mt5 = mt5 if mt5 is not None else mt5_module
        self._initialized = False
        self._coordinator = coordinator or MT5AccessCoordinator()
        self._account_generation = 0

    @contextmanager
    def operation(self, priority: AccessPriority = "market", name: str = "mt5") -> Iterator[None]:
        with self._coordinator.acquire(priority, name):
            yield

    def initialize(self) -> None:
        with self.operation("order", "initialize"):
            if self._initialized:
                return
            if self.mt5 is None:
                raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")
            path = self.settings.mt5_terminal_path.strip() or None
            kwargs: dict[str, object] = {
                "timeout": self.settings.mt5_timeout_ms,
                "portable": self.settings.mt5_portable,
            }
            if self.settings.mt5_login is not None:
                kwargs["login"] = self.settings.mt5_login
            if self.settings.mt5_password is not None:
                kwargs["password"] = self.settings.mt5_password.get_secret_value()
            if self.settings.mt5_server.strip():
                kwargs["server"] = self.settings.mt5_server.strip()

            initialized = bool(self.mt5.initialize(path, **kwargs)) if path else bool(self.mt5.initialize(**kwargs))
            if not initialized:
                raise MT5ClientError(f"MT5 initialize failed: {self.mt5.last_error()}")
            self._initialized = True
            logger.info(
                "MT5 initialized%s%s",
                f" path={path}" if path else "",
                f" login={self.settings.mt5_login}" if self.settings.mt5_login is not None else "",
            )


    @property
    def account_generation(self) -> int:
        return self._account_generation

    def switch_account(self, login: int, server: str) -> tuple[AccountState, AccountState]:
        server = server.strip()
        if not server:
            raise MT5ClientError("MT5 server is required")
        with self.operation("order", f"switch_account:{login}"):
            self.initialize()
            previous = account_state_from_mt5(self._account_info_locked())
            # Login is positional on the official MetaTrader5 Python binding.
            # Password is intentionally omitted so the terminal can use the
            # credentials previously saved for this account.
            switched = bool(
                self.mt5.login(
                    int(login),
                    server=server,
                    timeout=self.settings.mt5_timeout_ms,
                )
            )
            if not switched:
                raise MT5ClientError(f"MT5 login failed for {login} @ {server}: {self.mt5.last_error()}")
            current = account_state_from_mt5(self._account_info_locked())
            if current.login != int(login):
                raise MT5ClientError(f"MT5 switched to unexpected login {current.login}; requested {login}")
            if (current.server or "").strip().casefold() != server.casefold():
                raise MT5ClientError(
                    f"MT5 switched to unexpected server {current.server!r}; requested {server!r}"
                )
            if (previous.login, (previous.server or "").casefold()) != (current.login, (current.server or "").casefold()):
                self._account_generation += 1
            logger.warning(
                "MT5 account switched: previous_login=%s previous_server=%s login=%s server=%s generation=%s",
                previous.login, previous.server, current.login, current.server, self._account_generation,
            )
            return previous, current

    def _account_info_locked(self) -> Any:
        self._require_module()
        account_info = self.mt5.account_info()
        if account_info is None:
            raise MT5ClientError(f"MT5 account_info failed: {self.mt5.last_error()}")
        return account_info

    def shutdown(self) -> None:
        with self.operation("order", "shutdown"):
            if self.mt5 is not None and self._initialized:
                self.mt5.shutdown()
                self._initialized = False
                logger.info("MT5 shutdown completed")

    def get_account_info(self) -> Any:
        with self.operation("sync", "account_info"):
            return self._account_info_locked()

    def get_account_state(self) -> AccountState:
        return account_state_from_mt5(self.get_account_info())

    def get_terminal_info(self) -> Any:
        with self.operation("sync", "terminal_info"):
            self._require_module()
            terminal_info = self.mt5.terminal_info()
            if terminal_info is None:
                raise MT5ClientError(f"MT5 terminal_info failed: {self.mt5.last_error()}")
            return terminal_info

    def discover_terminal_accounts(self) -> list[dict[str, object]]:
        """Return accounts already used by this MT5 terminal without reading credentials.

        The official Python binding exposes only the currently connected account.
        MT5's documented data-folder layout, however, stores per-account trade
        databases under ``Bases/<server>/Trades/<login>``.  Reading those folder
        names gives us a safe, credential-free list of accounts that have been
        opened in this terminal.  ``accounts.dat`` is deliberately not parsed or
        modified.
        """
        self.initialize()
        active = self.get_account_state()
        terminal_info = self.get_terminal_info()
        candidates: dict[tuple[int, str], dict[str, object]] = {}

        def add(login: int | None, server: str | None, *, active_account: bool, source: str) -> None:
            if login is None or int(login) <= 0:
                return
            normalized_server = (server or "").strip()
            if not normalized_server:
                return
            key = (int(login), normalized_server.casefold())
            existing = candidates.get(key)
            if existing is None or (active_account and not bool(existing.get("active"))):
                candidates[key] = {
                    "login": int(login),
                    "server": normalized_server,
                    "active": active_account,
                    "source": source,
                }

        add(active.login, active.server, active_account=True, source="CURRENT")

        data_path_value = str(getattr(terminal_info, "data_path", "") or "").strip()
        if data_path_value:
            bases_dir = Path(data_path_value) / "Bases"
            try:
                server_dirs = list(bases_dir.iterdir()) if bases_dir.is_dir() else []
            except OSError as exc:
                logger.warning("Unable to inspect MT5 Bases directory %s: %s", bases_dir, exc)
                server_dirs = []

            for server_dir in server_dirs:
                if not server_dir.is_dir() or server_dir.name.casefold() == "default":
                    continue
                trades_dir = server_dir / "Trades"
                try:
                    account_dirs = list(trades_dir.iterdir()) if trades_dir.is_dir() else []
                except OSError as exc:
                    logger.debug("Unable to inspect MT5 Trades directory %s: %s", trades_dir, exc)
                    continue
                for account_dir in account_dirs:
                    if not account_dir.is_dir() or not account_dir.name.isdigit():
                        continue
                    login = int(account_dir.name)
                    is_active = (
                        active.login == login
                        and (active.server or "").strip().casefold() == server_dir.name.strip().casefold()
                    )
                    add(login, server_dir.name, active_account=is_active, source="TERMINAL_DATA")

        return sorted(
            candidates.values(),
            key=lambda item: (not bool(item["active"]), str(item["server"]).casefold(), int(item["login"])),
        )

    def is_connected(self) -> bool:
        try:
            terminal_info = self.get_terminal_info()
        except MT5ClientError:
            return False
        return bool(getattr(terminal_info, "connected", False))

    def select_symbol(self, broker_symbol: str) -> bool:
        with self.operation("market", f"symbol_select:{broker_symbol}"):
            self._require_module()
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

    def get_symbol_info(self, broker_symbol: str) -> Any | None:
        with self.operation("market", f"symbol_info:{broker_symbol}"):
            self._require_module()
            return self.mt5.symbol_info(broker_symbol)

    def get_latest_tick(self, broker_symbol: str) -> Any | None:
        with self.operation("market", f"latest_tick:{broker_symbol}"):
            self._require_module()
            tick = self.mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                logger.debug("No latest tick for %s: %s", broker_symbol, self.mt5.last_error())
            return tick

    def get_ticks_since(self, broker_symbol: str, since_datetime: datetime) -> list[Any]:
        with self.operation("market", f"ticks:{broker_symbol}"):
            self._require_module()
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

    def get_positions(self, broker_symbol: str | None = None) -> list[Any] | None:
        with self.operation("sync", f"positions_get:{broker_symbol or '*'}"):
            self._require_module()
            try:
                positions = self.mt5.positions_get(symbol=broker_symbol) if broker_symbol else self.mt5.positions_get()
            except TypeError:
                positions = self.mt5.positions_get()
            if positions is None:
                logger.warning("MT5 positions_get failed: %s", self.mt5.last_error())
                return None
            return list(positions)

    def get_history_deals(self, date_from: datetime, date_to: datetime) -> list[Any] | None:
        with self.operation("sync", "history_deals_get"):
            self._require_module()
            if not hasattr(self.mt5, "history_deals_get"):
                return []
            deals = self.mt5.history_deals_get(_ensure_utc(date_from), _ensure_utc(date_to))
            if deals is None:
                logger.warning("MT5 history_deals_get failed: %s", self.mt5.last_error())
                return None
            return list(deals)

    def get_rates(self, broker_symbol: str, timeframe: str = "D1", count: int = 120, start_pos: int = 1) -> list[dict[str, Any]]:
        with self.operation("sync", f"rates:{broker_symbol}:{timeframe}"):
            self._require_module()
            timeframe_id = _mt5_timeframe(self.mt5, timeframe)
            self.select_symbol(broker_symbol)
            rates = self.mt5.copy_rates_from_pos(broker_symbol, timeframe_id, max(0, start_pos), max(1, count))
            if rates is None:
                logger.warning("copy_rates_from_pos failed for %s %s: %s", broker_symbol, timeframe, self.mt5.last_error())
                return []
            return [_rate_to_payload(rates, row) for row in rates]

    def _require_module(self) -> None:
        if self.mt5 is None:
            raise MT5ClientError("MetaTrader5 package is not installed. Run: pip install -r requirements.txt")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mt5_timeframe(mt5: Any, timeframe: str) -> Any:
    normalized = timeframe.strip().upper()
    mapping = {
        "M1": "TIMEFRAME_M1",
        "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15",
        "H1": "TIMEFRAME_H1",
        "H2": "TIMEFRAME_H2",
        "H3": "TIMEFRAME_H3",
        "H4": "TIMEFRAME_H4",
        "D1": "TIMEFRAME_D1",
        "W1": "TIMEFRAME_W1",
    }
    return getattr(mt5, mapping.get(normalized, "TIMEFRAME_D1"))


def _rate_to_payload(rates: Any, row: Any) -> dict[str, Any]:
    names = getattr(getattr(rates, "dtype", None), "names", None)
    if names:
        return {name: _scalar(row[name]) for name in names}
    if hasattr(row, "_asdict"):
        return {key: _scalar(value) for key, value in row._asdict().items()}
    return dict(row)


def _scalar(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value

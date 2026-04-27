from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.health import BridgeHealth
from bridge.mt5_client import MT5Client, MT5ClientError
from bridge.symbol_mapper import SymbolMapper, SymbolMapping
from bridge.tick_buffer import TickBuffer

if TYPE_CHECKING:
    from bridge.backend_client import BackendClient

logger = logging.getLogger(__name__)


class TickDeduplicator:
    def __init__(self, max_keys: int = 200000) -> None:
        self.max_keys = max_keys
        self._seen: set[tuple[object, ...]] = set()

    def is_new(self, tick: dict[str, Any]) -> bool:
        key = (
            tick["internal_symbol"],
            tick["broker_symbol"],
            tick.get("time_msc"),
            tick["time"],
            tick.get("bid"),
            tick.get("ask"),
            tick.get("last"),
        )
        if key in self._seen:
            return False
        self._seen.add(key)
        if len(self._seen) > self.max_keys:
            self._seen = set(list(self._seen)[-self.max_keys // 2 :])
        return True


class TickCollector:
    def __init__(
        self,
        settings: BridgeSettings,
        mt5_client: MT5Client,
        backend_client: BackendClient,
        tick_buffer: TickBuffer,
    ) -> None:
        self.settings = settings
        self.mt5_client = mt5_client
        self.backend_client = backend_client
        self.tick_buffer = tick_buffer
        self.deduplicator = TickDeduplicator()
        self.health = BridgeHealth()
        self._stop_requested = False
        self._last_seen_by_symbol: dict[str, datetime] = {}
        self._last_status_post = 0.0
        self._last_diagnostic_log = 0.0
        self._diagnostic_sent_counts: dict[str, int] = {}
        self._diagnostic_latest_ticks: dict[str, dict[str, Any]] = {}

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self, once: bool = False) -> None:
        mappings: list[SymbolMapping] = []
        account: AccountState | None = None
        try:
            backend_symbols = self.backend_client.get_symbols()
            mappings = SymbolMapper(self.settings).load(backend_symbols)
            self.health.connected_to_backend = self.backend_client.health()

            self.mt5_client.initialize()
            self.health.connected_to_mt5 = self.mt5_client.is_connected()
            account = self.mt5_client.get_account_state()
            self._log_account(account)
            self._enforce_account_mode(account)

            active_mappings = self._select_symbols(mappings)
            self.health.active_symbols = [mapping.internal_symbol for mapping in active_mappings]
            self.health.account = account
            self.health.account_trade_mode = account.trade_mode
            self._post_status(force=True)

            self._recover_recent_ticks(active_mappings)
            self._flush(account=account, force=True)
            if once:
                return

            while not self._stop_requested:
                self._collect_poll(active_mappings)
                self._flush(account=account, force=False)
                self._post_status()
                self._log_market_diagnostics(active_mappings)
                time.sleep(self.settings.mt5_poll_interval_ms / 1000)
        except KeyboardInterrupt:
            logger.info("MT5 bridge interrupted by user")
        except Exception as exc:
            self.health.errors_count += 1
            self.health.message = str(exc)
            logger.exception("MT5 bridge stopped because of an error")
            self._post_status(force=True)
            raise
        finally:
            self._flush(account=account, force=True)
            self.mt5_client.shutdown()

    def _select_symbols(self, mappings: list[SymbolMapping]) -> list[SymbolMapping]:
        active: list[SymbolMapping] = []
        for mapping in mappings:
            logger.info(
                "MT5 mapping requested: %s -> %s display=%s enabled=%s tradable=%s analysis_only=%s",
                mapping.internal_symbol,
                mapping.broker_symbol,
                mapping.display_name,
                mapping.enabled,
                mapping.tradable,
                mapping.analysis_only,
            )
            if self.mt5_client.select_symbol(mapping.broker_symbol):
                active.append(mapping)
            else:
                self.health.errors_count += 1
        logger.info("Active MT5 symbols: %s", ", ".join(f"{m.internal_symbol}->{m.broker_symbol}" for m in active))
        return active

    def _recover_recent_ticks(self, mappings: list[SymbolMapping]) -> None:
        since = datetime.now(UTC) - timedelta(seconds=self.settings.mt5_lookback_seconds_on_start)
        logger.info("Recovering MT5 ticks from last %s seconds", self.settings.mt5_lookback_seconds_on_start)
        for mapping in mappings:
            self._collect_symbol(mapping, since)

    def _collect_poll(self, mappings: list[SymbolMapping]) -> None:
        now = datetime.now(UTC)
        for mapping in mappings:
            since = self._last_seen_by_symbol.get(mapping.internal_symbol, now - timedelta(seconds=1))
            self._collect_symbol(mapping, since)

    def _collect_symbol(self, mapping: SymbolMapping, since: datetime) -> None:
        raw_ticks = self.mt5_client.get_ticks_since(mapping.broker_symbol, since)
        converted_ticks: list[dict[str, Any]] = []
        for raw_tick in raw_ticks:
            tick = mt5_tick_to_torum(raw_tick, mapping)
            if tick is None or not self.deduplicator.is_new(tick):
                continue
            converted_ticks.append(tick)

        latest_raw_tick = self.mt5_client.get_latest_tick(mapping.broker_symbol)
        latest_tick = mt5_tick_to_torum(latest_raw_tick, mapping) if latest_raw_tick is not None else None
        if latest_tick is not None and self.deduplicator.is_new(latest_tick):
            converted_ticks.append(latest_tick)

        if not converted_ticks:
            return

        self.tick_buffer.add_many(converted_ticks)
        latest_tick = max(converted_ticks, key=lambda tick: int(tick.get("time_msc") or 0))
        latest_time = parse_iso_time(latest_tick["time"])
        self._last_seen_by_symbol[mapping.internal_symbol] = latest_time
        self.health.last_tick_time_by_symbol[mapping.internal_symbol] = latest_time
        self._diagnostic_sent_counts[mapping.internal_symbol] = self._diagnostic_sent_counts.get(mapping.internal_symbol, 0) + len(converted_ticks)
        self._diagnostic_latest_ticks[mapping.internal_symbol] = latest_tick
        logger.debug("Collected %s ticks for %s", len(converted_ticks), mapping.internal_symbol)

    def _flush(self, account: AccountState | None, force: bool) -> None:
        result = self.tick_buffer.flush(account=account.to_payload() if account else None, force=force)
        if result.inserted:
            self.health.ticks_sent_total += result.inserted
            self.health.last_batch_sent_at = datetime.now(UTC)

    def _post_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_status_post < 10:
            return
        self.health.connected_to_backend = self.backend_client.health()
        self.backend_client.post_status(self.health.to_payload())
        self._last_status_post = now

    def _log_market_diagnostics(self, mappings: list[SymbolMapping]) -> None:
        now = time.monotonic()
        if now - self._last_diagnostic_log < max(1, self.settings.mt5_diagnostic_log_interval_seconds):
            return
        for mapping in mappings:
            tick = self._diagnostic_latest_ticks.get(mapping.internal_symbol)
            if tick is None:
                logger.info("%s -> %s | no ticks collected yet | source=MT5", mapping.internal_symbol, mapping.broker_symbol)
                continue
            logger.info(
                "%s -> %s | bid=%s ask=%s time_msc=%s sent=%s source=MT5",
                mapping.internal_symbol,
                mapping.broker_symbol,
                tick.get("bid"),
                tick.get("ask"),
                tick.get("time_msc") or int(parse_iso_time(tick["time"]).timestamp() * 1000),
                self._diagnostic_sent_counts.get(mapping.internal_symbol, 0),
            )
            self._diagnostic_sent_counts[mapping.internal_symbol] = 0
        self._last_diagnostic_log = now

    def _log_account(self, account: AccountState) -> None:
        logger.info(
            "MT5 account connected: login=%s server=%s company=%s mode=%s balance=%s equity=%s",
            account.login,
            account.server,
            account.company,
            account.trade_mode,
            account.balance,
            account.equity,
        )
        if account.trade_mode == "REAL":
            logger.warning("REAL MT5 account detected. Phase 3 is market-data-only and will not place orders.")

    def _enforce_account_mode(self, account: AccountState) -> None:
        allowed = self.settings.allowed_account_modes
        if account.trade_mode not in allowed and account.trade_mode != "UNKNOWN":
            message = f"MT5 account mode {account.trade_mode} is not in MT5_ALLOWED_ACCOUNT_MODES={sorted(allowed)}"
            if account.trade_mode == "REAL" and self.settings.mt5_market_data_only:
                logger.warning("%s. Continuing in market-data-only mode.", message)
                return
            raise MT5ClientError(message)


def mt5_tick_to_torum(raw_tick: Any, mapping: SymbolMapping) -> dict[str, Any] | None:
    time_value = _get_tick_field(raw_tick, "time")
    time_msc = _get_tick_field(raw_tick, "time_msc")
    if time_msc:
        parsed_time_msc = int(float(time_msc))
        tick_time = datetime.fromtimestamp(parsed_time_msc / 1000, UTC)
    elif time_value:
        tick_time = datetime.fromtimestamp(float(time_value), UTC)
        parsed_time_msc = int(tick_time.timestamp() * 1000)
    else:
        return None

    bid = _positive_float_or_none(_get_tick_field(raw_tick, "bid"))
    ask = _positive_float_or_none(_get_tick_field(raw_tick, "ask"))
    last = _positive_float_or_none(_get_tick_field(raw_tick, "last"))
    volume = _float_or_zero(_get_tick_field(raw_tick, "volume_real"))
    if volume == 0:
        volume = _float_or_zero(_get_tick_field(raw_tick, "volume"))

    if bid is None and ask is None and last is None:
        return None

    return {
        "internal_symbol": mapping.internal_symbol,
        "broker_symbol": mapping.broker_symbol,
        "time": tick_time.isoformat().replace("+00:00", "Z"),
        "time_msc": parsed_time_msc,
        "bid": bid,
        "ask": ask,
        "last": last,
        "volume": volume,
    }


def parse_iso_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _get_tick_field(raw_tick: Any, field_name: str) -> Any:
    if hasattr(raw_tick, field_name):
        return getattr(raw_tick, field_name)
    try:
        value = raw_tick[field_name]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _positive_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0

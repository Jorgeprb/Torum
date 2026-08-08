from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any

from bridge.backend_client import BackendClient
from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client, MT5ClientError

logger = logging.getLogger(__name__)


class PositionSyncer:
    def __init__(self, settings: BridgeSettings, mt5_client: MT5Client, backend_client: BackendClient) -> None:
        self.settings = settings
        self.mt5_client = mt5_client
        self.backend_client = backend_client
        self._stop = Event()
        self._thread: Thread | None = None
        self._last_deals_sync_monotonic = 0.0
        self._cursor_loaded_for: str | None = None
        self._cursor_time_msc = 0
        self._cursor_ticket = 0
        self._startup_history_reconciled = not settings.mt5_startup_history_reconcile_enabled
        self._startup_history_due = monotonic() + max(0, settings.mt5_startup_history_reconcile_delay_seconds)

    def start(self) -> Thread:
        self._thread = Thread(target=self.run, name="torum-mt5-position-syncer", daemon=False)
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.error("Position syncer did not stop within %.1fs", timeout)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception:  # noqa: BLE001 - keep sync loop alive
                logger.exception("Unexpected MT5 position sync error")
            self._stop.wait(max(0.1, self.settings.mt5_position_sync_interval_seconds))

    def sync_once(self) -> dict[str, Any] | None:
        # Do not hold one giant MT5 lock around positions + up to a year of
        # deal history. MT5Client serializes each vendor call itself and gives
        # orders priority between calls, so a buy can pre-empt reconciliation.
        try:
            self.mt5_client.initialize()
            account_state = self.mt5_client.get_account_state()
            account = account_state.to_payload()
        except MT5ClientError as exc:
            logger.debug("Skipping position sync; MT5 unavailable: %s", exc)
            return None

        positions = self.mt5_client.get_positions()
        if positions is None:
            return None
        payload = [_position_to_payload(position, self.mt5_client.mt5) for position in positions]

        account_key = _account_key(account)
        self._ensure_cursor_loaded(account_key)
        history_events: list[dict[str, Any]] = []
        deals_checked = False
        now_mono = monotonic()
        if not self._startup_history_reconciled:
            if now_mono >= self._startup_history_due:
                history_events, deals_checked = self._load_full_history_deals()
                if deals_checked:
                    self._startup_history_reconciled = True
                    self._last_deals_sync_monotonic = now_mono
                    logger.info("MT5 startup history reconciliation loaded %s relevant events", len(history_events))
                else:
                    logger.warning("MT5 startup history reconciliation incomplete; will retry")
            # Before the configured startup delay, deliberately skip history.
            # The old elif branch accidentally loaded 365 days immediately.
        elif (
            self._last_deals_sync_monotonic == 0
            or now_mono - self._last_deals_sync_monotonic >= max(1, self.settings.mt5_deals_sync_interval_seconds)
        ):
            history_events, deals_checked = self._load_incremental_closed_deals()
            if deals_checked:
                self._last_deals_sync_monotonic = now_mono

        closed_deals = [event for event in history_events if event.get("history_category") != "cash_flow"]
        capital_flows = [event for event in history_events if event.get("history_category") == "cash_flow"]
        response = self.backend_client.post_positions_sync(
            payload,
            account,
            closed_deals,
            capital_flows,
            deals_checked=deals_checked,
        )
        if response is not None:
            if history_events and deals_checked:
                self._advance_cursor(history_events, account_key)
            logger.debug(
                "Synced MT5 positions: received=%s deals=%s created=%s updated=%s closed=%s",
                response.get("received"),
                response.get("deals_received"),
                response.get("created"),
                response.get("updated"),
                response.get("closed"),
            )
        return response

    def _history_date_to(self) -> datetime:
        # Some MT5 brokers expose deal timestamps in broker wall time while the
        # Python process runs in UTC.  Querying only up to real ``now`` then
        # misses a TP deal for several hours and leaves a ghost OPEN position.
        future_hours = max(1, min(24, int(self.settings.mt5_history_future_tolerance_hours)))
        return datetime.now(UTC) + timedelta(hours=future_hours)

    def _load_full_history_deals(self) -> tuple[list[dict[str, Any]], bool]:
        date_to = self._history_date_to()
        date_from = date_to - timedelta(days=max(1, self.settings.mt5_deals_history_lookback_days))
        return self._load_history_deals_chunked(date_from, date_to)

    def _load_incremental_closed_deals(self) -> tuple[list[dict[str, Any]], bool]:
        date_to = self._history_date_to()
        if self._cursor_time_msc > 0:
            overlap_ms = max(0, self.settings.mt5_deal_cursor_overlap_seconds) * 1000
            date_from = datetime.fromtimestamp(max(0, self._cursor_time_msc - overlap_ms) / 1000, UTC)
        else:
            date_from = date_to - timedelta(days=max(1, self.settings.mt5_deals_history_lookback_days))

        payloads, complete = self._load_history_deals_chunked(date_from, date_to)
        payloads = [
            payload
            for payload in payloads
            if _deal_cursor_key(payload) > (self._cursor_time_msc, self._cursor_ticket)
        ]
        payloads.sort(key=_deal_cursor_key)
        return payloads, complete

    def _load_history_deals_chunked(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Load history in short calls and report whether every chunk succeeded."""

        mt5 = self.mt5_client.mt5
        if mt5 is None:
            return [], False
        if date_from >= date_to:
            return [], True
        trade_types = {
            getattr(mt5, "DEAL_TYPE_BUY", 0),
            getattr(mt5, "DEAL_TYPE_SELL", 1),
        }
        cash_flow_types = _cash_flow_deal_types(mt5)
        chunk_days = max(1, int(self.settings.mt5_history_chunk_days))
        cursor = date_from
        by_key: dict[tuple[int, int], dict[str, Any]] = {}
        while cursor < date_to and not self._stop.is_set():
            chunk_end = min(date_to, cursor + timedelta(days=chunk_days))
            deals = self.mt5_client.get_history_deals(cursor, chunk_end)
            if deals is None:
                # Partial history cannot authoritatively prove that a timed-out
                # market request was never filled. Positive matches already
                # collected are still posted, but the backend will not release
                # an ambiguous reservation from this incomplete cycle.
                return [by_key[key] for key in sorted(by_key)], False
            for deal in deals:
                deal_type = getattr(deal, "type", None)
                position_id = getattr(deal, "position_id", None)
                if deal_type in trade_types and position_id:
                    payload = _deal_to_payload(deal)
                    payload["history_category"] = "trade"
                elif deal_type in cash_flow_types:
                    payload = _deal_to_payload(deal)
                    payload["history_category"] = "cash_flow"
                    payload["cash_flow_kind"] = _cash_flow_kind(payload.get("profit"))
                    payload["deal_type_name"] = cash_flow_types[deal_type]
                    # This project stores live MT5 chart/history timestamps in
                    # broker wall-clock form (UTC-tagged).  Tell the API which
                    # clock domain this cash movement belongs to so performance
                    # periods can normalize it to real UTC before TWR math.
                    payload["time_domain"] = "BROKER_CHART"
                else:
                    continue
                by_key[_deal_cursor_key(payload)] = payload
            cursor = chunk_end
        return [by_key[key] for key in sorted(by_key)], True

    def _ensure_cursor_loaded(self, account_key: str) -> None:
        if self._cursor_loaded_for == account_key:
            return
        self._cursor_loaded_for = account_key
        self._cursor_time_msc = 0
        self._cursor_ticket = 0
        path = self._cursor_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            cursor = payload.get(account_key) if isinstance(payload, dict) else None
            if isinstance(cursor, dict):
                self._cursor_time_msc = int(cursor.get("time_msc") or 0)
                self._cursor_ticket = int(cursor.get("ticket") or 0)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not load MT5 deal cursor %s: %s", path, exc)

    def _advance_cursor(self, deals: list[dict[str, Any]], account_key: str) -> None:
        if not deals:
            return
        newest = max((_deal_cursor_key(deal) for deal in deals), default=(0, 0))
        if newest <= (self._cursor_time_msc, self._cursor_ticket):
            return
        self._cursor_time_msc, self._cursor_ticket = newest
        path = self._cursor_path()
        try:
            payload: dict[str, Any] = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            payload[account_key] = {"time_msc": self._cursor_time_msc, "ticket": self._cursor_ticket}
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not persist MT5 deal cursor %s: %s", path, exc)

    def _cursor_path(self) -> Path:
        return Path(self.settings.mt5_deal_cursor_file).expanduser().resolve()


def _account_key(account: dict[str, Any]) -> str:
    return f"{account.get('login') or 'unknown'}::{account.get('server') or 'unknown'}"


def _position_to_payload(position: Any, mt5: Any) -> dict[str, Any]:
    raw = position._asdict() if hasattr(position, "_asdict") else {
        name: getattr(position, name)
        for name in dir(position)
        if not name.startswith("_")
    }
    position_type = raw.get("type")
    buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0) if mt5 is not None else 0
    side = "BUY" if position_type == buy_type else "SELL"
    ticket = raw.get("ticket")
    identifier = raw.get("identifier") or ticket
    return {
        **raw,
        "side": side,
        "position_ticket": ticket,
        "position_identifier": identifier,
        "raw": raw,
    }


def _deal_to_payload(deal: Any) -> dict[str, Any]:
    raw = deal._asdict() if hasattr(deal, "_asdict") else {
        name: getattr(deal, name)
        for name in dir(deal)
        if not name.startswith("_")
    }
    return {
        **raw,
        "position_id": raw.get("position_id"),
        "ticket": raw.get("ticket"),
        "time": raw.get("time"),
        "time_msc": raw.get("time_msc"),
        "price": raw.get("price"),
        "volume": raw.get("volume"),
        "type": raw.get("type"),
        "fee": raw.get("fee"),
        "profit": raw.get("profit"),
        "swap": raw.get("swap"),
        "commission": raw.get("commission"),
        "symbol": raw.get("symbol"),
        "entry": raw.get("entry"),
        "raw": raw,
    }



def _cash_flow_deal_types(mt5: Any) -> dict[int, str]:
    """MT5 balance-side events that must not inflate strategy return."""

    candidates = (
        ("DEAL_TYPE_BALANCE", 2, "BALANCE"),
        ("DEAL_TYPE_CREDIT", 3, "CREDIT"),
        ("DEAL_TYPE_CHARGE", 15, "CHARGE"),
        ("DEAL_TYPE_CORRECTION", 16, "CORRECTION"),
        ("DEAL_TYPE_BONUS", 17, "BONUS"),
    )
    result: dict[int, str] = {}
    for attr, fallback, label in candidates:
        value = getattr(mt5, attr, fallback)
        try:
            result[int(value)] = label
        except (TypeError, ValueError):
            continue
    return result


def _cash_flow_kind(amount: Any) -> str:
    try:
        value = float(amount or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0:
        return "DEPOSIT"
    if value < 0:
        return "WITHDRAWAL"
    return "ADJUSTMENT"

def _deal_cursor_key(deal: dict[str, Any]) -> tuple[int, int]:
    try:
        time_msc = int(deal.get("time_msc") or 0)
    except (TypeError, ValueError):
        time_msc = int(float(deal.get("time") or 0) * 1000)
    try:
        ticket = int(deal.get("ticket") or deal.get("deal") or 0)
    except (TypeError, ValueError):
        ticket = 0
    return time_msc, ticket


def _load_closed_deals(
    mt5: Any,
    lookback_days: int,
    *,
    future_tolerance_hours: int = 14,
) -> list[dict[str, Any]]:
    """Backward-compatible broad history loader used by startup/reconciliation tests.

    Despite the historic name, all BUY/SELL trade deals are returned because entry
    deals are required to aggregate a complete position history.  The live syncer
    uses the incremental cursor path above instead of calling this every second.
    """
    future_hours = max(1, min(24, int(future_tolerance_hours)))
    date_to = datetime.now(UTC) + timedelta(hours=future_hours)
    date_from = date_to - timedelta(days=max(1, int(lookback_days)))
    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        return []
    trade_types = {
        getattr(mt5, "DEAL_TYPE_BUY", 0),
        getattr(mt5, "DEAL_TYPE_SELL", 1),
    }
    payloads: list[dict[str, Any]] = []
    for deal in deals:
        if not getattr(deal, "position_id", None):
            continue
        deal_type = getattr(deal, "type", None)
        if deal_type is not None and deal_type not in trade_types:
            continue
        payloads.append(_deal_to_payload(deal))
    payloads.sort(key=_deal_cursor_key)
    return payloads

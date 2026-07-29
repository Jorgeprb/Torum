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
        with self.mt5_client.operation("sync", "position_sync"):
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
            closed_deals: list[dict[str, Any]] = []
            now_mono = monotonic()
            if not self._startup_history_reconciled and now_mono >= self._startup_history_due:
                closed_deals = self._load_full_history_deals()
                self._startup_history_reconciled = True
                self._last_deals_sync_monotonic = now_mono
                logger.info("MT5 startup history reconciliation loaded %s deals", len(closed_deals))
            elif (
                self._last_deals_sync_monotonic == 0
                or now_mono - self._last_deals_sync_monotonic >= max(1, self.settings.mt5_deals_sync_interval_seconds)
            ):
                closed_deals = self._load_incremental_closed_deals()
                self._last_deals_sync_monotonic = now_mono

        response = self.backend_client.post_positions_sync(payload, account, closed_deals)
        if response is not None:
            if closed_deals:
                self._advance_cursor(closed_deals, account_key)
            logger.debug(
                "Synced MT5 positions: received=%s deals=%s created=%s updated=%s closed=%s",
                response.get("received"),
                response.get("deals_received"),
                response.get("created"),
                response.get("updated"),
                response.get("closed"),
            )
        return response

    def _load_full_history_deals(self) -> list[dict[str, Any]]:
        date_to = datetime.now(UTC) + timedelta(seconds=1)
        date_from = date_to - timedelta(days=max(1, self.settings.mt5_deals_history_lookback_days))
        deals = self.mt5_client.get_history_deals(date_from, date_to)
        if deals is None:
            return []
        mt5 = self.mt5_client.mt5
        if mt5 is None:
            return []
        trade_types = {getattr(mt5, "DEAL_TYPE_BUY", 0), getattr(mt5, "DEAL_TYPE_SELL", 1)}
        payloads = [
            _deal_to_payload(deal)
            for deal in deals
            if getattr(deal, "position_id", None)
            and (getattr(deal, "type", None) is None or getattr(deal, "type", None) in trade_types)
        ]
        payloads.sort(key=_deal_cursor_key)
        return payloads

    def _load_incremental_closed_deals(self) -> list[dict[str, Any]]:
        date_to = datetime.now(UTC) + timedelta(seconds=1)
        if self._cursor_time_msc > 0:
            overlap_ms = max(0, self.settings.mt5_deal_cursor_overlap_seconds) * 1000
            date_from = datetime.fromtimestamp(max(0, self._cursor_time_msc - overlap_ms) / 1000, UTC)
        else:
            date_from = date_to - timedelta(days=max(1, self.settings.mt5_deals_history_lookback_days))

        deals = self.mt5_client.get_history_deals(date_from, date_to)
        if deals is None:
            return []
        mt5 = self.mt5_client.mt5
        if mt5 is None:
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
            payload = _deal_to_payload(deal)
            key = _deal_cursor_key(payload)
            if key <= (self._cursor_time_msc, self._cursor_ticket):
                continue
            payloads.append(payload)
        payloads.sort(key=_deal_cursor_key)
        return payloads

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


def _load_closed_deals(mt5: Any, lookback_days: int) -> list[dict[str, Any]]:
    """Backward-compatible broad history loader used by startup/reconciliation tests.

    Despite the historic name, all BUY/SELL trade deals are returned because entry
    deals are required to aggregate a complete position history.  The live syncer
    uses the incremental cursor path above instead of calling this every second.
    """
    date_to = datetime.now(UTC) + timedelta(seconds=1)
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

import logging
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
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

    def start(self) -> Thread:
        self._thread = Thread(target=self.run, name="torum-mt5-position-syncer", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            self.sync_once()
            self._stop.wait(max(1, self.settings.mt5_position_sync_interval_seconds))

    def sync_once(self) -> dict[str, Any] | None:
        try:
            self.mt5_client.initialize()
            account = self.mt5_client.get_account_state().to_payload()
        except MT5ClientError as exc:
            logger.debug("Skipping position sync; MT5 unavailable: %s", exc)
            return None

        mt5 = self.mt5_client.mt5
        if mt5 is None or not hasattr(mt5, "positions_get"):
            return None

        positions = mt5.positions_get()
        if positions is None:
            logger.warning("MT5 positions_get failed: %s", mt5.last_error() if hasattr(mt5, "last_error") else None)
            return None

        payload = [_position_to_payload(position, mt5) for position in positions]
        closed_deals = _load_closed_deals(mt5, self.settings.mt5_deals_history_lookback_days)
        response = self.backend_client.post_positions_sync(payload, account, closed_deals)
        if response is not None:
            logger.info(
                "Synced MT5 positions: received=%s deals=%s created=%s updated=%s closed=%s",
                response.get("received"),
                response.get("deals_received"),
                response.get("created"),
                response.get("updated"),
                response.get("closed"),
            )
        return response


def _position_to_payload(position: Any, mt5: Any) -> dict[str, Any]:
    raw = position._asdict() if hasattr(position, "_asdict") else {
        name: getattr(position, name)
        for name in dir(position)
        if not name.startswith("_")
    }
    position_type = raw.get("type")
    buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0)
    side = "BUY" if position_type == buy_type else "SELL"
    return {
        **raw,
        "side": side,
        "raw": raw,
    }


def _load_closed_deals(mt5: Any, lookback_days: int) -> list[dict[str, Any]]:
    if not hasattr(mt5, "history_deals_get"):
        return []

    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=max(1, lookback_days))
    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        logger.warning("MT5 history_deals_get failed: %s", mt5.last_error() if hasattr(mt5, "last_error") else None)
        return []

    trade_types = {
        getattr(mt5, "DEAL_TYPE_BUY", 0),
        getattr(mt5, "DEAL_TYPE_SELL", 1),
    }
    return [
        _deal_to_payload(deal)
        for deal in deals
        if getattr(deal, "position_id", None)
        and (getattr(deal, "type", None) is None or getattr(deal, "type", None) in trade_types)
    ]


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

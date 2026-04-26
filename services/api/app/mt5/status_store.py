from datetime import UTC, datetime
from threading import Lock

from app.mt5.schemas import MT5StatusPayload, MT5StatusRead


class MT5StatusStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._status = MT5StatusRead()

    def get(self) -> MT5StatusRead:
        with self._lock:
            return self._status.model_copy(deep=True)

    def update(self, payload: MT5StatusPayload) -> MT5StatusRead:
        with self._lock:
            self._status = MT5StatusRead(**payload.model_dump(), updated_at=datetime.now(UTC))
            return self._status.model_copy(deep=True)

    def update_from_tick_batch(
        self,
        source: str,
        inserted_ticks: int,
        last_tick_time_by_symbol: dict[str, datetime],
        account_trade_mode: str = "UNKNOWN",
    ) -> MT5StatusRead | None:
        if source.upper() != "MT5":
            return None

        with self._lock:
            current = self._status.model_copy(deep=True)
            merged_tick_times = dict(current.last_tick_time_by_symbol)
            merged_tick_times.update(last_tick_time_by_symbol)
            current.connected_to_mt5 = True
            current.connected_to_backend = True
            current.account_trade_mode = account_trade_mode  # type: ignore[assignment]
            current.last_tick_time_by_symbol = merged_tick_times
            current.ticks_sent_total += inserted_ticks
            current.last_batch_sent_at = datetime.now(UTC)
            current.updated_at = datetime.now(UTC)
            self._status = current
            return current.model_copy(deep=True)


mt5_status_store = MT5StatusStore()

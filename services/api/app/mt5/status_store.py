from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from time import monotonic

from app.core.config import get_settings
from app.core.distributed_state import distributed_state
from app.mt5.schemas import MT5StatusPayload, MT5StatusRead

_DISTRIBUTED_KEY = "mt5:status"
_DISTRIBUTED_TTL_SECONDS = 10 * 60
_REMOTE_REFRESH_SECONDS = 1.0


class MT5StatusStore:
    """Fast local MT5 status with optional Redis replication across API workers."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._status = MT5StatusRead()
        self._last_remote_refresh = 0.0

    def get(self) -> MT5StatusRead:
        now = monotonic()
        should_refresh = (
            not get_settings().enforce_single_worker
            and now - self._last_remote_refresh >= _REMOTE_REFRESH_SECONDS
        )
        if should_refresh:
            self._last_remote_refresh = now
            remote = distributed_state.get_json(_DISTRIBUTED_KEY)
            if isinstance(remote, dict):
                try:
                    remote_status = MT5StatusRead.model_validate(remote)
                except (TypeError, ValueError):
                    remote_status = None
                if remote_status is not None:
                    with self._lock:
                        local_updated = self._status.updated_at
                        remote_updated = remote_status.updated_at
                        if remote_updated is not None and (local_updated is None or remote_updated > local_updated):
                            self._status = remote_status
        with self._lock:
            return self._status.model_copy(deep=True)

    def update(self, payload: MT5StatusPayload) -> MT5StatusRead:
        with self._lock:
            self._status = MT5StatusRead(**payload.model_dump(), updated_at=datetime.now(UTC))
            snapshot = self._status.model_copy(deep=True)
        self._publish(snapshot)
        return snapshot

    def update_from_tick_batch(
        self,
        source: str,
        inserted_ticks: int,
        last_tick_time_by_symbol: dict[str, datetime],
        account_trade_mode: str = "UNKNOWN",
        account=None,
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

            if account is not None:
                current.account = account

            current.last_tick_time_by_symbol = merged_tick_times
            current.ticks_sent_total += inserted_ticks
            current.last_batch_sent_at = datetime.now(UTC)
            current.updated_at = datetime.now(UTC)

            self._status = current
            snapshot = current.model_copy(deep=True)
        self._publish(snapshot)
        return snapshot

    @staticmethod
    def _publish(snapshot: MT5StatusRead) -> None:
        if get_settings().enforce_single_worker:
            return
        distributed_state.set_json(
            _DISTRIBUTED_KEY,
            snapshot.model_dump(mode="json"),
            ttl_seconds=_DISTRIBUTED_TTL_SECONDS,
        )


mt5_status_store = MT5StatusStore()

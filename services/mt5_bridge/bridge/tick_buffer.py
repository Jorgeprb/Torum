from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bridge.backend_client import BackendClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FlushResult:
    submitted: int = 0
    inserted: int = 0
    duplicates_ignored: int = 0


class TickBuffer:
    def __init__(
        self,
        backend_client: BackendClient,
        batch_max_size: int,
        flush_interval_seconds: float,
        max_buffer_size: int,
    ) -> None:
        self.backend_client = backend_client
        self.batch_max_size = batch_max_size
        self.flush_interval_seconds = flush_interval_seconds
        self.max_buffer_size = max_buffer_size
        self._ticks: list[dict[str, Any]] = []
        self._last_flush_monotonic = time.monotonic()

    @property
    def size(self) -> int:
        return len(self._ticks)

    def add_many(self, ticks: list[dict[str, Any]]) -> int:
        if not ticks:
            return 0

        self._ticks.extend(ticks)
        dropped = 0
        if len(self._ticks) > self.max_buffer_size:
            dropped = len(self._ticks) - self.max_buffer_size
            self._ticks = self._ticks[dropped:]
            logger.error("MT5 tick buffer exceeded max size. Dropped oldest %s ticks", dropped)
        return dropped

    def should_flush(self) -> bool:
        if not self._ticks:
            return False
        if len(self._ticks) >= self.batch_max_size:
            return True
        return (time.monotonic() - self._last_flush_monotonic) >= self.flush_interval_seconds

    def flush(self, account: dict[str, Any] | None, force: bool = False) -> FlushResult:
        result = FlushResult()
        while self._ticks and (force or self.should_flush()):
            batch = self._ticks[: self.batch_max_size]
            try:
                response = self.backend_client.post_ticks_batch(batch, account=account, source="MT5")
            except Exception as exc:
                logger.error("Could not flush %s MT5 ticks to backend: %s", len(batch), exc)
                break

            submitted = int(response.get("received", len(batch)))
            inserted = int(response.get("inserted", response.get("accepted_ticks", len(batch))))
            duplicates = int(response.get("duplicates_ignored", max(0, submitted - inserted)))

            result.submitted += submitted
            result.inserted += inserted
            result.duplicates_ignored += duplicates
            self._ticks = self._ticks[len(batch) :]
            self._last_flush_monotonic = time.monotonic()
            logger.info(
                "Sent MT5 batch: submitted=%s inserted=%s duplicates=%s candles_updated=%s",
                submitted,
                inserted,
                duplicates,
                response.get("candles_updated", response.get("updated_candles")),
            )
            if not force:
                break

        if result.submitted:
            logger.debug("MT5 flush finished at %s", datetime.now(UTC).isoformat())
        return result

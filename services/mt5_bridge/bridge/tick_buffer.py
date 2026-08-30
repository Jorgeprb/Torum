from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
import logging
from threading import Condition, Thread
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
    dropped: int = 0

    def __iadd__(self, other: "FlushResult") -> "FlushResult":
        self.submitted += other.submitted
        self.inserted += other.inserted
        self.duplicates_ignored += other.duplicates_ignored
        self.dropped += other.dropped
        return self


class TickBuffer:
    """Thread-safe tick queue with a dedicated HTTP sender.

    MT5 polling never waits for backend HTTP retries. The sender preserves order,
    applies backpressure by dropping the oldest ticks only after max_buffer_size,
    and can drain synchronously during shutdown.
    """

    def __init__(
        self,
        backend_client: BackendClient,
        batch_max_size: int,
        flush_interval_seconds: float,
        max_buffer_size: int,
    ) -> None:
        self.backend_client = backend_client
        self.batch_max_size = max(1, batch_max_size)
        self.flush_interval_seconds = max(0.01, flush_interval_seconds)
        self.max_buffer_size = max(1, max_buffer_size)
        # Each queued tick carries the MT5 account that produced it. This is
        # critical when the terminal changes account while old ticks are still
        # waiting for the HTTP sender: no batch can be attributed to the new
        # account accidentally.
        self._ticks: deque[tuple[dict[str, Any], dict[str, Any] | None]] = deque()
        self._condition = Condition()
        self._last_flush_monotonic = time.monotonic()
        self._latest_account: dict[str, Any] | None = None
        self._force_flush = False
        self._stop = False
        self._thread: Thread | None = None
        self._totals = FlushResult()
        self._reported = FlushResult()
        self._last_summary_log = time.monotonic()

    @property
    def size(self) -> int:
        with self._condition:
            return len(self._ticks)

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = False
            self._thread = Thread(target=self._run, name="torum-tick-sender", daemon=False)
            self._thread.start()

    def add_many(self, ticks: list[dict[str, Any]], account: dict[str, Any] | None = None) -> int:
        if not ticks:
            return 0
        account_snapshot = dict(account) if account is not None else None
        with self._condition:
            self._ticks.extend((tick, account_snapshot) for tick in ticks)
            dropped = 0
            while len(self._ticks) > self.max_buffer_size:
                self._ticks.popleft()
                dropped += 1
            if dropped:
                self._totals.dropped += dropped
                logger.error("MT5 tick buffer exceeded max size. Dropped oldest %s ticks", dropped)
            if len(self._ticks) >= self.batch_max_size:
                self._condition.notify_all()
            return dropped

    def flush(self, account: dict[str, Any] | None, force: bool = False, timeout: float = 15.0) -> FlushResult:
        # Preserve deterministic synchronous semantics for callers that have not
        # explicitly started the asynchronous sender (notably one-shot tools and
        # tests). The production collector calls start() before entering its poll
        # loop, so normal tick collection remains fully decoupled from HTTP.
        with self._condition:
            thread_started = self._thread is not None
        if not thread_started:
            return self._flush_inline(account=account, force=force)

        deadline = time.monotonic() + max(0.1, timeout)
        with self._condition:
            if account is not None:
                self._latest_account = account
            if force:
                self._force_flush = True
            self._condition.notify_all()
            if force:
                while self._ticks and time.monotonic() < deadline:
                    self._condition.wait(timeout=min(0.25, max(0.0, deadline - time.monotonic())))
            return self._unreported_locked()

    def _flush_inline(self, account: dict[str, Any] | None, force: bool) -> FlushResult:
        result = FlushResult()
        while True:
            with self._condition:
                if not self._ticks:
                    break
                due = force or len(self._ticks) >= self.batch_max_size or (
                    time.monotonic() - self._last_flush_monotonic
                ) >= self.flush_interval_seconds
                if not due:
                    break
                batch, batch_account = self._peek_batch_locked(account)
            response = self.backend_client.post_ticks_batch(batch, account=batch_account, source="MT5")
            submitted = int(response.get("received", len(batch)))
            inserted = int(response.get("inserted", response.get("accepted_ticks", len(batch))))
            duplicates = int(response.get("duplicates_ignored", max(0, submitted - inserted)))
            with self._condition:
                for _ in range(min(len(batch), len(self._ticks))):
                    self._ticks.popleft()
                self._totals.submitted += submitted
                self._totals.inserted += inserted
                self._totals.duplicates_ignored += duplicates
                self._last_flush_monotonic = time.monotonic()
            result.submitted += submitted
            result.inserted += inserted
            result.duplicates_ignored += duplicates
            if not force:
                break
        with self._condition:
            # Keep the public accounting cursor consistent with asynchronous calls.
            self._reported = FlushResult(
                submitted=self._totals.submitted,
                inserted=self._totals.inserted,
                duplicates_ignored=self._totals.duplicates_ignored,
                dropped=self._totals.dropped,
            )
            result.dropped = self._totals.dropped
        return result

    def stop(self, account: dict[str, Any] | None = None, *, flush: bool = True, timeout: float = 20.0) -> FlushResult:
        result = FlushResult()
        if flush:
            result += self.flush(account=account, force=True, timeout=timeout / 2)
        with self._condition:
            self._stop = True
            self._force_flush = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.1, timeout / 2))
            if thread.is_alive():
                logger.error("Tick sender did not stop within timeout; unsent=%s", self.size)
        with self._condition:
            result += self._unreported_locked()
        return result

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._should_send_locked() and not self._stop:
                    timeout = max(0.01, self.flush_interval_seconds - (time.monotonic() - self._last_flush_monotonic))
                    self._condition.wait(timeout=timeout)
                if self._stop and not self._ticks:
                    self._condition.notify_all()
                    return
                if not self._ticks:
                    self._force_flush = False
                    continue
                batch, account = self._peek_batch_locked(self._latest_account)

            try:
                response = self.backend_client.post_ticks_batch(batch, account=account, source="MT5")
            except Exception as exc:  # noqa: BLE001 - transport boundary
                logger.warning("Could not flush %s MT5 ticks to backend: %s", len(batch), exc)
                with self._condition:
                    self._last_flush_monotonic = time.monotonic()
                    self._condition.wait(timeout=0.25)
                continue

            submitted = int(response.get("received", len(batch)))
            inserted = int(response.get("inserted", response.get("accepted_ticks", len(batch))))
            duplicates = int(response.get("duplicates_ignored", max(0, submitted - inserted)))
            with self._condition:
                remove_count = min(len(batch), len(self._ticks))
                for _ in range(remove_count):
                    self._ticks.popleft()
                self._totals.submitted += submitted
                self._totals.inserted += inserted
                self._totals.duplicates_ignored += duplicates
                self._last_flush_monotonic = time.monotonic()
                if not self._ticks:
                    self._force_flush = False
                self._condition.notify_all()

            logger.debug(
                "Sent MT5 batch: submitted=%s inserted=%s duplicates=%s candles_updated=%s",
                submitted,
                inserted,
                duplicates,
                response.get("candles_updated", response.get("updated_candles")),
            )
            now = time.monotonic()
            if now - self._last_summary_log >= 10:
                logger.info(
                    "MT5 tick sender summary submitted=%s inserted=%s duplicates=%s queued=%s dropped=%s at=%s",
                    self._totals.submitted,
                    self._totals.inserted,
                    self._totals.duplicates_ignored,
                    self.size,
                    self._totals.dropped,
                    datetime.now(UTC).isoformat(),
                )
                self._last_summary_log = now

    def _peek_batch_locked(
        self, fallback_account: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Return one account-homogeneous batch without removing it.

        Legacy callers/tests may enqueue untagged ticks; for those, the account
        supplied to flush remains the fallback. Tagged production ticks always
        keep the account snapshot captured at collection time.
        """

        if not self._ticks:
            return [], fallback_account
        first_tick, first_account = self._ticks[0]
        batch_account = first_account if first_account is not None else fallback_account
        batch_key = _account_identity(batch_account)
        batch = [first_tick]
        for tick, tagged_account in islice(self._ticks, 1, self.batch_max_size):
            effective_account = tagged_account if tagged_account is not None else fallback_account
            if _account_identity(effective_account) != batch_key:
                break
            batch.append(tick)
        return batch, batch_account

    def _should_send_locked(self) -> bool:
        if not self._ticks:
            return False
        if self._force_flush or len(self._ticks) >= self.batch_max_size:
            return True
        return (time.monotonic() - self._last_flush_monotonic) >= self.flush_interval_seconds

    def _unreported_locked(self) -> FlushResult:
        result = FlushResult(
            submitted=self._totals.submitted - self._reported.submitted,
            inserted=self._totals.inserted - self._reported.inserted,
            duplicates_ignored=self._totals.duplicates_ignored - self._reported.duplicates_ignored,
            dropped=self._totals.dropped - self._reported.dropped,
        )
        self._reported = FlushResult(
            submitted=self._totals.submitted,
            inserted=self._totals.inserted,
            duplicates_ignored=self._totals.duplicates_ignored,
            dropped=self._totals.dropped,
        )
        return result


def _account_identity(account: dict[str, Any] | None) -> tuple[int | None, str]:
    if not account:
        return None, ""
    login = account.get("login")
    try:
        parsed_login = int(login) if login is not None else None
    except (TypeError, ValueError):
        parsed_login = None
    return parsed_login, str(account.get("server") or "").strip().casefold()

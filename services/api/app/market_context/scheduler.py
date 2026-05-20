from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Event, Thread

from app.db.session import SessionLocal
from app.market_context.dollar_strength import DollarStrengthService

logger = logging.getLogger(__name__)


class DollarStrengthScheduler:
    def __init__(self) -> None:
        self._thread: Thread | None = None
        self._stop = Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="dollar-strength-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        self._recompute_if_needed()
        while not self._stop.wait(3600):
            self._recompute_if_needed()

    def _recompute_if_needed(self) -> None:
        try:
            with SessionLocal() as db:
                service = DollarStrengthService(db)
                latest = service.latest_snapshot()
                now = datetime.now(UTC)
                if latest is None or latest.valid_until is None or latest.valid_until <= now:
                    service.recompute()
                    logger.info("Dollar strength snapshot recomputed")
        except Exception as exc:
            logger.warning("Dollar strength scheduler failed: %s", exc)


dollar_strength_scheduler = DollarStrengthScheduler()

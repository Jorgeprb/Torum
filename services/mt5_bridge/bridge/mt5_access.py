from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Condition, get_ident
from time import perf_counter
from typing import Iterator, Literal

logger = logging.getLogger(__name__)
AccessPriority = Literal["order", "sync", "market"]


class MT5AccessCoordinator:
    """Serialize all calls to the MetaTrader5 Python API.

    The vendor module is process-global and does not document concurrent access as
    safe. Orders get priority over polling/history work. The lock is re-entrant for
    a thread so a high-level operation can safely call MT5Client helper methods.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._owner_thread_id: int | None = None
        self._depth = 0
        self._waiting_orders = 0

    @contextmanager
    def acquire(self, priority: AccessPriority = "market", operation: str = "mt5") -> Iterator[None]:
        thread_id = get_ident()
        started = perf_counter()
        is_order = priority == "order"
        with self._condition:
            if self._owner_thread_id == thread_id:
                self._depth += 1
            else:
                if is_order:
                    self._waiting_orders += 1
                try:
                    while self._owner_thread_id is not None or (not is_order and self._waiting_orders > 0):
                        self._condition.wait(timeout=0.5)
                    self._owner_thread_id = thread_id
                    self._depth = 1
                finally:
                    if is_order:
                        self._waiting_orders -= 1

        waited_ms = (perf_counter() - started) * 1000
        if waited_ms >= 100:
            logger.info("mt5_access_wait operation=%s priority=%s wait_ms=%.2f", operation, priority, waited_ms)
        try:
            yield
        finally:
            with self._condition:
                if self._owner_thread_id != thread_id:
                    logger.error("mt5_access_owner_mismatch operation=%s", operation)
                    return
                self._depth -= 1
                if self._depth == 0:
                    self._owner_thread_id = None
                    self._condition.notify_all()

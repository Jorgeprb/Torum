from __future__ import annotations

import atexit
import logging
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import Full, Queue

from app.core.config import get_settings
from app.core.decision_log import TimestampedSizeRotatingFileHandler, decision_logger

_CONFIGURED = False
_TRACE_LISTENER: QueueListener | None = None
_TRACE_QUEUE: Queue[logging.LogRecord] | None = None
_ROOT_LISTENER: QueueListener | None = None
_ROOT_QUEUE: Queue[logging.LogRecord] | None = None


class NonBlockingQueueHandler(QueueHandler):
    """Enqueue diagnostic records without ever waiting on disk I/O."""

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except Full:
            # Diagnostics are deliberately best-effort. A saturated log queue
            # must never delay or block a market order.
            return


def _stop_trace_listener() -> None:
    global _TRACE_LISTENER, _ROOT_LISTENER
    root_listener = _ROOT_LISTENER
    _ROOT_LISTENER = None
    if root_listener is not None:
        try:
            root_listener.stop()
        except Exception:  # noqa: BLE001 - shutdown logging is best-effort
            pass
    listener = _TRACE_LISTENER
    _TRACE_LISTENER = None
    if listener is not None:
        try:
            listener.stop()
        except Exception:  # noqa: BLE001 - shutdown logging is best-effort
            pass


def configure_logging() -> None:
    global _CONFIGURED, _TRACE_LISTENER, _TRACE_QUEUE, _ROOT_LISTENER, _ROOT_QUEUE
    if _CONFIGURED:
        return

    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root_sinks: list[logging.Handler] = [console]
    log_root = Path(settings.log_directory)
    if settings.log_to_files:
        api_handler = TimestampedSizeRotatingFileHandler(
            log_root / "api",
            prefix="torum_api",
            suffix="log",
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
        api_handler.setLevel(logging.INFO)
        api_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        root_sinks.append(api_handler)

    # Docker console writes and rotating-file I/O are not allowed to block the
    # candle-close order path.  A bounded best-effort queue preserves normal
    # diagnostics while dropping excess records instead of delaying a buy.
    _ROOT_QUEUE = Queue(maxsize=20_000)
    root_queue_handler = NonBlockingQueueHandler(_ROOT_QUEUE)
    root_queue_handler.setLevel(logging.INFO)
    root.addHandler(root_queue_handler)
    _ROOT_LISTENER = QueueListener(
        _ROOT_QUEUE,
        *root_sinks,
        respect_handler_level=True,
    )
    _ROOT_LISTENER.start()

    trace_logger = decision_logger()
    trace_logger.handlers.clear()
    trace_logger.setLevel(logging.INFO if settings.strategy_trace_enabled else logging.CRITICAL)
    trace_logger.propagate = False
    if settings.strategy_trace_enabled:
        trace_file_handler = TimestampedSizeRotatingFileHandler(
            log_root / "strategy",
            prefix="torum_strategy_decisions",
            suffix="jsonl",
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
        trace_file_handler.setLevel(logging.INFO)
        trace_file_handler.setFormatter(logging.Formatter("%(message)s"))
        _TRACE_QUEUE = Queue(maxsize=10_000)
        queue_handler = NonBlockingQueueHandler(_TRACE_QUEUE)
        queue_handler.setLevel(logging.INFO)
        trace_logger.addHandler(queue_handler)
        _TRACE_LISTENER = QueueListener(
            _TRACE_QUEUE,
            trace_file_handler,
            respect_handler_level=True,
        )
        _TRACE_LISTENER.start()
    atexit.register(_stop_trace_listener)

    _CONFIGURED = True

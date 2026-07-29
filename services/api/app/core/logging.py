from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.decision_log import TimestampedSizeRotatingFileHandler, decision_logger

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
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
    root.addHandler(console)

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
        root.addHandler(api_handler)

    trace_logger = decision_logger()
    trace_logger.handlers.clear()
    trace_logger.setLevel(logging.INFO if settings.strategy_trace_enabled else logging.CRITICAL)
    trace_logger.propagate = False
    if settings.strategy_trace_enabled:
        trace_handler = TimestampedSizeRotatingFileHandler(
            log_root / "strategy",
            prefix="torum_strategy_decisions",
            suffix="jsonl",
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
        trace_handler.setLevel(logging.INFO)
        trace_handler.setFormatter(logging.Formatter("%(message)s"))
        trace_logger.addHandler(trace_handler)

    _CONFIGURED = True

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
import json
import logging
import os
from pathlib import Path
from threading import RLock, current_thread
from typing import Any

from app.core.config import get_settings
from app.core.request_context import get_request_id

_DECISION_LOGGER_NAME = "torum.strategy.decision"
_REDACTED_KEYS = ("password", "secret", "token", "authorization", "cookie", "api_key", "private_key")


class TimestampedSizeRotatingFileHandler(logging.Handler):
    """Write logs to timestamped files and rotate when they reach a size limit.

    A dedicated file is created for every process.  Rotation names include UTC
    time, PID and a monotonic sequence, which keeps files readable on Windows
    and avoids collisions during Docker restarts.
    """

    terminator = "\n"

    def __init__(
        self,
        directory: str | Path,
        *,
        prefix: str,
        suffix: str,
        max_bytes: int,
        backup_count: int,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.prefix = prefix
        self.suffix = suffix.lstrip(".")
        self.max_bytes = max(1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self.encoding = encoding
        self._lock = RLock()
        self._stream: Any | None = None
        self._path: Path | None = None
        self._sequence = 0
        self._open_new_file()

    @property
    def current_path(self) -> Path | None:
        return self._path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + self.terminator
            encoded_size = len(message.encode(self.encoding, errors="replace"))
            with self._lock:
                if self._stream is None:
                    self._open_new_file()
                if self._current_size() + encoded_size > self.max_bytes:
                    self._open_new_file()
                assert self._stream is not None
                self._stream.write(message)
                self._stream.flush()
        except Exception:  # noqa: BLE001 - logging must never break trading
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.flush()
                    self._stream.close()
                finally:
                    self._stream = None
        super().close()

    def _current_size(self) -> int:
        if self._path is None:
            return 0
        try:
            return self._path.stat().st_size
        except OSError:
            return 0

    def _open_new_file(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._stream is not None:
            self._stream.flush()
            self._stream.close()
        self._sequence += 1
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{self.prefix}_{timestamp}_pid{os.getpid()}_{self._sequence:03d}.{self.suffix}"
        self._path = self.directory / filename
        self._stream = self._path.open("a", encoding=self.encoding, buffering=1)
        self._prune_old_files()

    def _prune_old_files(self) -> None:
        pattern = f"{self.prefix}_*.{self.suffix}"
        try:
            files = sorted(
                self.directory.glob(pattern),
                key=lambda item: (item.stat().st_mtime_ns, item.name),
            )
        except OSError:
            return
        for old_file in files[:-self.backup_count]:
            if old_file == self._path:
                continue
            try:
                old_file.unlink(missing_ok=True)
            except OSError:
                continue


def decision_logger() -> logging.Logger:
    return logging.getLogger(_DECISION_LOGGER_NAME)


def trace_event(stage: str, event: str, /, **fields: Any) -> None:
    """Append one structured JSON event to the Torum decision trace.

    This function intentionally swallows every serialization/logging error so a
    diagnostic feature can never alter strategy execution.
    """

    try:
        settings = get_settings()
        if not settings.strategy_trace_enabled:
            return
        payload: dict[str, Any] = {
            "schema_version": 1,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "stage": str(stage),
            "event": str(event),
            "request_id": get_request_id() or None,
            "process_id": os.getpid(),
            "thread": current_thread().name,
        }
        payload.update(fields)
        safe_payload = _json_safe(payload)
        decision_logger().info(json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    except Exception:  # noqa: BLE001 - diagnostics must never affect execution
        return


def trace_exception(stage: str, event: str, exc: BaseException, /, **fields: Any) -> None:
    trace_event(
        stage,
        event,
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        **fields,
    )


def _json_safe(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if key is not None and any(token in key.lower() for token in _REDACTED_KEYS):
        return "<redacted>"
    if depth > 12:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 8000 else value[:8000] + "…<truncated>"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return _json_safe(value.value, key=key, depth=depth + 1)
    if is_dataclass(value):
        return _json_safe(asdict(value), key=key, depth=depth + 1)
    if isinstance(value, dict):
        return {
            str(item_key): _json_safe(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(mode="json"), key=key, depth=depth + 1)
        except Exception:  # noqa: BLE001
            pass
    rendered = repr(value)
    return rendered if len(rendered) <= 2000 else rendered[:2000] + "…<truncated>"

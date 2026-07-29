from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any


class TimestampedSizeRotatingFileHandler(logging.Handler):
    def __init__(
        self,
        directory: str | Path,
        *,
        max_bytes: int = 10_000_000,
        backup_count: int = 20,
    ) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.max_bytes = max(1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self._lock = RLock()
        self._stream: Any | None = None
        self._path: Path | None = None
        self._sequence = 0
        self._open_new_file()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + "\n"
            with self._lock:
                if self._stream is None or self._size() + len(message.encode("utf-8", errors="replace")) > self.max_bytes:
                    self._open_new_file()
                assert self._stream is not None
                self._stream.write(message)
                self._stream.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.flush()
                self._stream.close()
                self._stream = None
        super().close()

    def _size(self) -> int:
        try:
            return self._path.stat().st_size if self._path is not None else 0
        except OSError:
            return 0

    def _open_new_file(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self._stream is not None:
            self._stream.flush()
            self._stream.close()
        self._sequence += 1
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        self._path = self.directory / f"torum_mt5_bridge_{stamp}_pid{os.getpid()}_{self._sequence:03d}.log"
        self._stream = self._path.open("a", encoding="utf-8", buffering=1)
        self._prune()

    def _prune(self) -> None:
        try:
            files = sorted(
                self.directory.glob("torum_mt5_bridge_*.log"),
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


def configure_logging(
    level: str,
    *,
    log_to_file: bool = True,
    log_directory: str | None = None,
    max_bytes: int = 10_000_000,
    backup_count: int = 20,
) -> None:
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(resolved_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    console = logging.StreamHandler()
    console.setLevel(resolved_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_to_file:
        default_directory = Path(__file__).resolve().parents[3] / "logs" / "mt5_bridge"
        file_handler = TimestampedSizeRotatingFileHandler(
            log_directory or default_directory,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

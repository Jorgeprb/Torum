from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.session import SessionLocal
from app.strategies.models import StrategyConfig
from app.strategies.schemas import TorumV1BacktestRead, TorumV1BacktestRequest
from app.strategies.torum_v1_backtest import (
    TorumV1BacktestCancelled,
    TorumV1BacktestEngine,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
_JOB_TTL = timedelta(hours=2)
_MAX_RETAINED_JOBS = 30


@dataclass(slots=True)
class _BacktestJob:
    id: str
    user_id: int
    config_id: int
    request: TorumV1BacktestRequest
    status: str = "QUEUED"
    progress: float = 0.0
    stage: str = "QUEUED"
    message: str = "Simulación en cola"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TorumV1BacktestRead | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class TorumV1BacktestJobManager:
    """Process-local backtest queue with progress and cooperative cancellation.

    Torum currently runs the API with a single worker because several live-market
    stores are process-local. Keeping simulation results local avoids serializing
    very large candle/debug payloads into Redis while still allowing the browser
    to reconnect to an in-flight job during the same API process lifetime.
    """

    def __init__(self, *, max_workers: int = 2) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, _BacktestJob] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="torum-backtest",
        )

    def start(
        self,
        *,
        user_id: int,
        config_id: int,
        request: TorumV1BacktestRequest,
    ) -> dict[str, Any]:
        self._prune()
        job = _BacktestJob(
            id=uuid.uuid4().hex,
            user_id=user_id,
            config_id=config_id,
            request=request.model_copy(deep=True),
        )
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job.id)
        return self._snapshot(job, include_result=False)

    def get(
        self,
        *,
        job_id: str,
        user_id: int,
        include_result: bool = True,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user_id != user_id:
                return None
            return self._snapshot(job, include_result=include_result)

    def cancel(self, *, job_id: str, user_id: int) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user_id != user_id:
                return None
            if job.status not in _TERMINAL_STATUSES:
                job.cancel_event.set()
                job.status = "CANCELLING"
                job.stage = "CANCELLING"
                job.message = "Cancelando simulación"
            return self._snapshot(job, include_result=False)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.cancel_event.is_set():
                self._mark_cancelled(job)
                return
            job.status = "RUNNING"
            job.stage = "PREPARING"
            job.message = "Preparando simulación"
            job.started_at = datetime.now(UTC)

        try:
            with SessionLocal() as db:
                config = db.get(StrategyConfig, job.config_id)
                if config is None or config.user_id != job.user_id:
                    raise RuntimeError("strategy_config_not_found")
                result = TorumV1BacktestEngine(db).run(
                    config,
                    job.request,
                    progress_callback=lambda progress, stage, message: self._update_progress(
                        job.id,
                        progress,
                        stage,
                        message,
                    ),
                    cancel_check=job.cancel_event.is_set,
                )
            with self._lock:
                current = self._jobs.get(job.id)
                if current is None:
                    return
                if current.cancel_event.is_set():
                    self._mark_cancelled(current)
                    return
                current.result = result
                current.progress = 1.0
                current.status = "COMPLETED"
                current.stage = "COMPLETED"
                current.message = "Simulación completada"
                current.completed_at = datetime.now(UTC)
                current.error = None
        except TorumV1BacktestCancelled:
            with self._lock:
                current = self._jobs.get(job.id)
                if current is not None:
                    self._mark_cancelled(current)
        except Exception as exc:  # noqa: BLE001 - worker boundary
            logger.exception("torum_backtest_job_failed job_id=%s", job.id)
            with self._lock:
                current = self._jobs.get(job.id)
                if current is None:
                    return
                current.status = "FAILED"
                current.stage = "FAILED"
                current.message = "La simulación ha fallado"
                current.error = str(exc)[:4000]
                current.completed_at = datetime.now(UTC)

    def _update_progress(
        self,
        job_id: str,
        progress: float,
        stage: str,
        message: str,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in _TERMINAL_STATUSES:
                return
            job.progress = max(job.progress, max(0.0, min(1.0, float(progress))))
            job.stage = stage
            job.message = message

    @staticmethod
    def _mark_cancelled(job: _BacktestJob) -> None:
        job.status = "CANCELLED"
        job.stage = "CANCELLED"
        job.message = "Simulación cancelada"
        job.completed_at = datetime.now(UTC)
        job.result = None
        job.error = None

    @staticmethod
    def _snapshot(job: _BacktestJob, *, include_result: bool) -> dict[str, Any]:
        return {
            "job_id": job.id,
            "status": job.status,
            "progress": round(job.progress, 6),
            "stage": job.stage,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "result": job.result if include_result and job.status == "COMPLETED" else None,
            "error": job.error,
        }

    def _prune(self) -> None:
        cutoff = datetime.now(UTC) - _JOB_TTL
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in _TERMINAL_STATUSES
                and job.completed_at is not None
                and job.completed_at < cutoff
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
            if len(self._jobs) <= _MAX_RETAINED_JOBS:
                return
            completed = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.status in _TERMINAL_STATUSES
                ),
                key=lambda item: item.completed_at or item.created_at,
            )
            for job in completed[: max(0, len(self._jobs) - _MAX_RETAINED_JOBS)]:
                self._jobs.pop(job.id, None)


backtest_job_manager = TorumV1BacktestJobManager()

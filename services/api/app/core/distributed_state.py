from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

try:  # Optional at import time so unit tests can run without Redis installed.
    import redis  # type: ignore
except ImportError:  # pragma: no cover - exercised in minimal test environments
    redis = None  # type: ignore[assignment]


class DistributedState:
    """Small Redis-backed state facade with safe process-local fallback."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._disabled_until = 0.0
        self._client_lock = threading.Lock()

    def _redis(self) -> Any | None:
        if redis is None or time.monotonic() < self._disabled_until:
            return None
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                client = redis.Redis.from_url(
                    get_settings().redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.5,
                    health_check_interval=30,
                )
                client.ping()
                self._client = client
            except Exception as exc:  # Redis is an acceleration layer, not a startup dependency.
                self._disabled_until = time.monotonic() + 15.0
                logger.debug("distributed_state_unavailable error=%s", exc)
                return None
        return self._client

    def get_json(self, key: str) -> Any | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(self._key(key))
            return json.loads(raw) if raw else None
        except Exception as exc:
            self._mark_failed(exc)
            return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> bool:
        client = self._redis()
        if client is None:
            return False
        try:
            client.set(self._key(key), json.dumps(value, separators=(",", ":"), default=str), ex=ttl_seconds)
            return True
        except Exception as exc:
            self._mark_failed(exc)
            return False

    def delete(self, key: str) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            client.delete(self._key(key))
        except Exception as exc:
            self._mark_failed(exc)

    def delete_pattern(self, pattern: str) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            cursor = 0
            redis_pattern = self._key(pattern)
            while True:
                cursor, keys = client.scan(cursor=cursor, match=redis_pattern, count=100)
                if keys:
                    client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            self._mark_failed(exc)

    def publish_json(self, channel: str, value: Any) -> bool:
        client = self._redis()
        if client is None:
            return False
        try:
            client.publish(
                self._key(f"channel:{channel}"),
                json.dumps(value, separators=(",", ":"), default=str),
            )
            return True
        except Exception as exc:
            self._mark_failed(exc)
            return False

    def consume_json(
        self,
        channel: str,
        stop_event: threading.Event,
        callback,
    ) -> None:
        """Consume a Redis pub/sub channel until stopped; safe no-op without Redis."""
        while not stop_event.is_set():
            client = self._redis()
            if client is None:
                stop_event.wait(1.0)
                continue
            pubsub = None
            try:
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(self._key(f"channel:{channel}"))
                while not stop_event.is_set():
                    message = pubsub.get_message(timeout=1.0)
                    if not message or message.get("type") != "message":
                        continue
                    raw = message.get("data")
                    try:
                        value = json.loads(raw) if isinstance(raw, str) else None
                    except json.JSONDecodeError:
                        continue
                    if value is not None:
                        callback(value)
            except Exception as exc:
                self._mark_failed(exc)
                stop_event.wait(1.0)
            finally:
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:
                        pass

    def acquire_lock(self, key: str, token: str, ttl_seconds: int) -> bool:
        client = self._redis()
        if client is None:
            return True
        try:
            return bool(client.set(self._key(f"lock:{key}"), token, nx=True, ex=ttl_seconds))
        except Exception as exc:
            self._mark_failed(exc)
            return True

    def release_lock(self, key: str, token: str) -> None:
        client = self._redis()
        if client is None:
            return
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        try:
            client.eval(script, 1, self._key(f"lock:{key}"), token)
        except Exception as exc:
            self._mark_failed(exc)

    @staticmethod
    def _key(key: str) -> str:
        return f"torum:{key}"

    def _mark_failed(self, exc: Exception) -> None:
        logger.debug("distributed_state_operation_failed error=%s", exc)
        self._client = None
        self._disabled_until = time.monotonic() + 15.0


distributed_state = DistributedState()

_LOCAL_LOCK_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}


@dataclass
class HybridLock:
    """Thread lock plus Redis lease, preserving the standard acquire/release API."""

    key: str
    lease_seconds: int = 120
    _token: str | None = None
    _local: threading.Lock | None = None

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        with _LOCAL_LOCK_GUARD:
            local = _LOCAL_LOCKS.setdefault(self.key, threading.Lock())
        self._local = local
        if timeout is None or timeout < 0:
            local_acquired = local.acquire(blocking)
            deadline = None
        else:
            local_acquired = local.acquire(blocking, timeout)
            deadline = time.monotonic() + timeout
        if not local_acquired:
            return False

        token = uuid.uuid4().hex
        while not distributed_state.acquire_lock(self.key, token, self.lease_seconds):
            if not blocking or (deadline is not None and time.monotonic() >= deadline):
                local.release()
                self._local = None
                return False
            time.sleep(0.05)
        self._token = token
        return True

    def release(self) -> None:
        if self._token is not None:
            distributed_state.release_lock(self.key, self._token)
            self._token = None
        if self._local is not None:
            self._local.release()
            self._local = None

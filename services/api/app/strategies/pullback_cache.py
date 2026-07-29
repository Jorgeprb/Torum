from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.core.distributed_state import distributed_state
from app.strategies.models import StrategyConfig
from app.strategies.torum_v1 import TORUM_V1_KEY, pullback_debug_payload
from app.ticks.models import Tick


@dataclass(slots=True)
class _CacheEntry:
    candle_time: datetime | None
    params_hash: str
    payload: list[dict[str, Any]]
    created_at: datetime


_LOCK = RLock()
_CACHE: dict[tuple[int, str], _CacheEntry] = {}
_DISTRIBUTED_TTL_SECONDS = 24 * 60 * 60


def _distributed_key(user_id: int, symbol: str) -> str:
    return f"pullbacks:{user_id}:{symbol.upper()}:M5"


def _entry_to_json(entry: _CacheEntry) -> dict[str, Any]:
    return {
        "candle_time": entry.candle_time.isoformat() if entry.candle_time else None,
        "params_hash": entry.params_hash,
        "payload": entry.payload,
        "created_at": entry.created_at.isoformat(),
    }


def _entry_from_json(value: Any) -> _CacheEntry | None:
    if not isinstance(value, dict):
        return None
    try:
        candle_raw = value.get("candle_time")
        created_raw = value.get("created_at")
        payload = value.get("payload")
        digest = value.get("params_hash")
        if not isinstance(payload, list) or not isinstance(digest, str) or not isinstance(created_raw, str):
            return None
        candle_time = datetime.fromisoformat(candle_raw) if isinstance(candle_raw, str) and candle_raw else None
        created_at = datetime.fromisoformat(created_raw)
        if candle_time is not None and candle_time.tzinfo is None:
            candle_time = candle_time.replace(tzinfo=UTC)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return _CacheEntry(candle_time, digest, [dict(item) for item in payload if isinstance(item, dict)], created_at)
    except (TypeError, ValueError):
        return None


def _params_hash(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_pullbacks(
    db: Session,
    *,
    user_id: int,
    symbol: str,
    force: bool = False,
    candle_limit: int = 600,
) -> tuple[list[dict[str, Any]], bool, datetime | None]:
    normalized_symbol = symbol.upper()
    config = db.scalar(
        select(StrategyConfig)
        .where(
            StrategyConfig.user_id == user_id,
            StrategyConfig.strategy_key == TORUM_V1_KEY,
            StrategyConfig.internal_symbol == normalized_symbol,
        )
        .order_by(StrategyConfig.id)
        .limit(1)
    )
    params = {"pullback_min_pct": 0.0, "pullback_max_count": 10, **(config.params_json if config else {})}
    if config is None or not bool(params.get("pullback_enabled", True)):
        return [], True, None

    candles = list(
        db.scalars(
            select(Candle)
            .where(Candle.internal_symbol == normalized_symbol, Candle.timeframe == "M5")
            .order_by(Candle.time.desc())
            .limit(max(100, min(2000, candle_limit)))
        )
    )
    candles.reverse()
    latest_candle_time = candles[-1].time if candles else None
    digest = _params_hash(params)
    cache_key = (user_id, normalized_symbol)

    with _LOCK:
        cached = _CACHE.get(cache_key)
    if not force and cached is None:
        cached = _entry_from_json(distributed_state.get_json(_distributed_key(user_id, normalized_symbol)))
        if cached is not None:
            with _LOCK:
                _CACHE[cache_key] = cached
    if (
        not force
        and cached is not None
        and cached.candle_time == latest_candle_time
        and cached.params_hash == digest
    ):
        return [dict(item) for item in cached.payload], True, cached.created_at

    latest_tick = db.scalar(
        select(Tick)
        .where(Tick.internal_symbol == normalized_symbol)
        .order_by(Tick.time_msc.desc().nullslast(), Tick.time.desc())
        .limit(1)
    )
    live_price = None
    live_time = None
    if latest_tick is not None:
        live_price = latest_tick.bid or latest_tick.last or latest_tick.ask
        live_time = latest_tick.time

    payload = pullback_debug_payload(
        candles,
        params,
        live_price=live_price,
        live_time=live_time,
        live_cache_key=f"user:{user_id}:{normalized_symbol}:M5:pullbacks",
    )
    now = datetime.now(UTC)
    entry = _CacheEntry(latest_candle_time, digest, [dict(item) for item in payload], now)
    with _LOCK:
        _CACHE[cache_key] = entry
    distributed_state.set_json(
        _distributed_key(user_id, normalized_symbol),
        _entry_to_json(entry),
        ttl_seconds=_DISTRIBUTED_TTL_SECONDS,
    )
    return payload, False, now


def invalidate_pullback_cache(*, user_id: int | None = None, symbol: str | None = None) -> None:
    normalized_symbol = symbol.upper() if symbol else None
    with _LOCK:
        keys = list(_CACHE)
        for key in keys:
            if user_id is not None and key[0] != user_id:
                continue
            if normalized_symbol is not None and key[1] != normalized_symbol:
                continue
            _CACHE.pop(key, None)
    if user_id is not None and normalized_symbol is not None:
        distributed_state.delete(_distributed_key(user_id, normalized_symbol))
    elif user_id is not None:
        distributed_state.delete_pattern(f"pullbacks:{user_id}:*:M5")
    elif normalized_symbol is not None:
        distributed_state.delete_pattern(f"pullbacks:*:{normalized_symbol}:M5")
    else:
        distributed_state.delete_pattern("pullbacks:*:M5")

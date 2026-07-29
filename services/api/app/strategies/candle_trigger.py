from __future__ import annotations

from datetime import datetime
from threading import RLock

from app.candles.models import Candle
from app.core.decision_log import trace_event

_LOCK = RLock()
_LAST_M5_BUCKET: dict[str, datetime] = {}


def symbols_with_newly_closed_m5(candles: list[Candle]) -> list[str]:
    """Return each symbol once when its M5 bucket advances.

    The current bucket remains live. A transition from bucket A to B means A is
    now closed and is the only moment the M5 entry strategy needs evaluating.
    """
    latest_by_symbol: dict[str, datetime] = {}
    for candle in candles:
        if str(candle.timeframe).upper() != "M5":
            continue
        current = latest_by_symbol.get(candle.internal_symbol)
        if current is None or candle.time > current:
            latest_by_symbol[candle.internal_symbol] = candle.time

    closed: list[str] = []
    transitions: list[dict[str, object]] = []
    with _LOCK:
        for symbol, bucket in latest_by_symbol.items():
            previous = _LAST_M5_BUCKET.get(symbol)
            advanced = previous is None or bucket > previous
            transitions.append({"symbol": symbol, "previous_bucket": previous, "current_bucket": bucket, "advanced": advanced})
            # On process startup, evaluate once as well: the current bucket is
            # live but the previous M5 candle in the database is already closed.
            # Strategy-level idempotency prevents duplicate orders.
            if advanced:
                closed.append(symbol)
                _LAST_M5_BUCKET[symbol] = bucket
    if closed:
        trace_event(
            "strategy_trigger",
            "m5_bucket_advanced",
            transitions=[item for item in transitions if item["advanced"]],
            scheduled_symbols=sorted(set(closed)),
        )
    return sorted(set(closed))


def clear_candle_trigger_state() -> None:
    with _LOCK:
        _LAST_M5_BUCKET.clear()

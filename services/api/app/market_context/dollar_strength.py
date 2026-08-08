from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import prod
from threading import RLock
from time import monotonic
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.market_context.models import DollarStrengthSnapshot
from app.market_context.schemas import DollarStrengthRead
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError

DXY_SYMBOL = "DXY"
DXY_TIMEFRAME = "D1"
DXY_SOURCE = "synthetic_dxy"
DXY_BASE = 50.14348112
DXY_COMPONENTS: tuple[tuple[str, float], ...] = (
    ("EURUSD", -0.576),
    ("USDJPY", 0.136),
    ("GBPUSD", -0.119),
    ("USDCAD", 0.091),
    ("USDSEK", 0.042),
    ("USDCHF", 0.036),
)

_LATEST_SNAPSHOT_CACHE: dict[int, tuple[DollarStrengthRead, float]] = {}
_LATEST_SNAPSHOT_CACHE_LOCK = RLock()


DEFAULT_USD_STRENGTH_PARAMS: dict[str, object] = {
    "usd_strength_filter_enabled": True,
    "usd_strength_apply_to_symbols": ["XAUUSD", "XAUEUR"],
    "usd_strength_mode": "only_operate_when_weak",
    "usd_sma_period": 30,
    "usd_neutral_band_points": 0.10,
    "usd_allow_when_neutral": False,
    "usd_strong_drop_override_enabled": True,
    "usd_strong_drop_lookback_days": 3,
    "usd_strong_drop_min_pct": 0.45,
    "usd_strong_drop_require_bearish_close": True,
    "usd_strength_strict": False,
}


@dataclass(frozen=True, slots=True)
class DollarStrengthDecision:
    enabled: bool
    allowed: bool
    reason: str
    metadata: dict[str, object]


class DollarStrengthService:
    def __init__(self, db: Session, mt5_client: MT5BridgeClient | None = None) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()

    def latest_snapshot(self) -> DollarStrengthSnapshot | None:
        return self.db.scalar(select(DollarStrengthSnapshot).order_by(DollarStrengthSnapshot.updated_at.desc(), DollarStrengthSnapshot.id.desc()).limit(1))

    def latest_snapshot_read(self) -> DollarStrengthRead:
        cache_key = id(self.db.get_bind())
        with _LATEST_SNAPSHOT_CACHE_LOCK:
            cached = _LATEST_SNAPSHOT_CACHE.get(cache_key)
        if cached is not None:
            cached_read, cached_at = cached
            now = datetime.now(UTC)
            valid_until = cached_read.valid_until
            if valid_until is not None and valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=UTC)
            cache_ttl = 3600.0 if cached_read.updated_at is not None else 30.0
            if monotonic() - cached_at < cache_ttl and (valid_until is None or valid_until > now):
                return cached_read
        snapshot = self.latest_snapshot()
        read = unknown_snapshot_read() if snapshot is None else DollarStrengthRead.model_validate(snapshot)
        with _LATEST_SNAPSHOT_CACHE_LOCK:
            _LATEST_SNAPSHOT_CACHE[cache_key] = (read, monotonic())
        return read

    def recompute(self, *, params: dict[str, object] | None = None, count: int = 120) -> DollarStrengthRead:
        merged_params = merged_usd_strength_params(params)
        missing: list[str] = []
        error_message: str | None = None
        candles_by_symbol: dict[str, list[dict[str, object]]] = {}

        try:
            candles_by_symbol = self._load_pair_rates_from_bridge(count)
        except Exception as exc:
            error_message = str(exc)
            candles_by_symbol = self._load_pair_candles_from_db(count)

        missing = [symbol for symbol, _ in DXY_COMPONENTS if not candles_by_symbol.get(symbol)]
        if missing:
            read = classify_dollar_strength([], params=merged_params, missing_symbols=missing, error_message=error_message)
            return self._store_snapshot(read)

        synthetic = build_synthetic_dxy_candles(candles_by_symbol)
        if synthetic:
            self._upsert_dxy_candles(synthetic)
        read = classify_dollar_strength(synthetic, params=merged_params, missing_symbols=[], error_message=error_message)
        return self._store_snapshot(read)

    def _load_pair_rates_from_bridge(self, count: int) -> dict[str, list[dict[str, object]]]:
        if not self.mt5_client.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        return {symbol: self.mt5_client.get_rates(symbol, DXY_TIMEFRAME, count=count) for symbol, _ in DXY_COMPONENTS}

    def _load_pair_candles_from_db(self, count: int) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {}
        for symbol, _ in DXY_COMPONENTS:
            rows = list(
                self.db.scalars(
                    select(Candle)
                    .where(Candle.internal_symbol == symbol, Candle.timeframe == DXY_TIMEFRAME)
                    .order_by(Candle.time.desc())
                    .limit(count)
                )
            )
            rows.reverse()
            result[symbol] = [_candle_payload(row) for row in rows]
        return result

    def _upsert_dxy_candles(self, rows: list[dict[str, object]]) -> None:
        for row in rows:
            time_value = _ensure_datetime(row["time"])
            existing = self.db.get(Candle, (time_value, DXY_SYMBOL, DXY_TIMEFRAME))
            if existing is None:
                self.db.add(
                    Candle(
                        time=time_value,
                        internal_symbol=DXY_SYMBOL,
                        timeframe=DXY_TIMEFRAME,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                        tick_count=int(row.get("tick_count") or 1),
                        first_tick_time_msc=None,
                        last_tick_time_msc=None,
                        source=DXY_SOURCE,
                    )
                )
            else:
                existing.open = float(row["open"])
                existing.high = float(row["high"])
                existing.low = float(row["low"])
                existing.close = float(row["close"])
                existing.volume = float(row.get("volume") or 0.0)
                existing.tick_count = int(row.get("tick_count") or 1)
                existing.source = DXY_SOURCE
        self.db.commit()

    def _store_snapshot(self, read: DollarStrengthRead) -> DollarStrengthRead:
        snapshot = DollarStrengthSnapshot(
            symbol=read.symbol,
            dxy_value=read.dxy_value,
            sma30=read.sma30,
            difference=read.difference,
            state=read.state,
            trading_allowed=read.trading_allowed,
            reason=read.reason,
            slope_days=read.slope_days,
            slope_pct=read.slope_pct,
            strong_drop_override_active=read.strong_drop_override_active,
            source=read.source,
            valid_until=read.valid_until,
            missing_symbols=list(read.missing_symbols),
            symbols_used=list(read.symbols_used),
            error_message=read.error_message,
            stale=read.stale,
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        read = DollarStrengthRead.model_validate(snapshot)
        cache_key = id(self.db.get_bind())
        with _LATEST_SNAPSHOT_CACHE_LOCK:
            _LATEST_SNAPSHOT_CACHE[cache_key] = (read, monotonic())
        return read


def clear_dollar_strength_snapshot_cache() -> None:
    """Clear all process-local DXY snapshot caches (tests/reloads)."""
    with _LATEST_SNAPSHOT_CACHE_LOCK:
        _LATEST_SNAPSHOT_CACHE.clear()


def build_synthetic_dxy_candles(candles_by_symbol: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    by_time: dict[int, dict[str, dict[str, object]]] = {}
    for symbol, _ in DXY_COMPONENTS:
        for row in candles_by_symbol.get(symbol, []):
            timestamp = int(_ensure_datetime(row["time"]).timestamp())
            by_time.setdefault(timestamp, {})[symbol] = row

    rows: list[dict[str, object]] = []
    for timestamp in sorted(by_time):
        components = by_time[timestamp]
        if any(symbol not in components for symbol, _ in DXY_COMPONENTS):
            continue
        values_open = []
        values_close = []
        values_high = []
        values_low = []
        for symbol, exponent in DXY_COMPONENTS:
            row = components[symbol]
            open_value = _positive_float(row.get("open"))
            close_value = _positive_float(row.get("close"))
            high_value = _positive_float(row.get("high"))
            low_value = _positive_float(row.get("low"))
            if None in (open_value, close_value, high_value, low_value):
                break
            values_open.append(open_value ** exponent)  # type: ignore[operator]
            values_close.append(close_value ** exponent)  # type: ignore[operator]
            values_high.append((high_value if exponent > 0 else low_value) ** exponent)  # type: ignore[operator]
            values_low.append((low_value if exponent > 0 else high_value) ** exponent)  # type: ignore[operator]
        else:
            rows.append(
                {
                    "time": datetime.fromtimestamp(timestamp, tz=UTC),
                    "open": DXY_BASE * prod(values_open),
                    "high": DXY_BASE * prod(values_high),
                    "low": DXY_BASE * prod(values_low),
                    "close": DXY_BASE * prod(values_close),
                    "volume": 0.0,
                    "tick_count": 1,
                }
            )
    return rows


def classify_dollar_strength(
    dxy_candles: list[dict[str, object]],
    *,
    params: dict[str, object] | None = None,
    missing_symbols: list[str] | None = None,
    error_message: str | None = None,
) -> DollarStrengthRead:
    merged = merged_usd_strength_params(params)
    sma_period = _int_param(merged.get("usd_sma_period"), 30)
    strict = _bool_param(merged.get("usd_strength_strict"), False)
    missing = missing_symbols or []
    now = datetime.now(UTC)
    valid_until = now + timedelta(days=1)
    symbols_used = [symbol for symbol, _ in DXY_COMPONENTS if symbol not in missing]

    sorted_rows = sorted(dxy_candles, key=lambda row: _ensure_datetime(row["time"]))
    closes = [_positive_float(row.get("close")) for row in sorted_rows]
    closes = [value for value in closes if value is not None]
    if missing or len(closes) < sma_period:
        return DollarStrengthRead(
            symbol=DXY_SYMBOL,
            state="UNKNOWN",
            trading_allowed=not strict,
            reason="usd_strength_unknown",
            slope_days=_int_param(merged.get("usd_strong_drop_lookback_days"), 3),
            source="synthetic_mt5",
            updated_at=now,
            valid_until=valid_until,
            missing_symbols=missing,
            symbols_used=symbols_used,
            error_message=error_message,
            stale=bool(error_message and closes),
        )

    latest = float(closes[-1])
    latest_open = _positive_float(sorted_rows[-1].get("open")) or latest
    sma = sum(closes[-sma_period:]) / sma_period
    difference = latest - sma
    band = _nonnegative_float_param(merged.get("usd_neutral_band_points"), 0.10)
    allow_neutral = _bool_param(merged.get("usd_allow_when_neutral"), False)
    slope_days = _int_param(merged.get("usd_strong_drop_lookback_days"), 3)
    slope_pct = None
    if len(closes) > slope_days and closes[-1 - slope_days] > 0:
        slope_pct = (latest - closes[-1 - slope_days]) / closes[-1 - slope_days] * 100

    state = "UNKNOWN"
    allowed = not strict
    reason = "usd_strength_unknown"
    override = False

    if latest < sma - band:
        state = "WEAK"
        allowed = True
        reason = "dxy_below_sma30"
    elif abs(difference) <= band:
        state = "NEUTRAL"
        allowed = allow_neutral
        reason = "dxy_neutral_zone"
    else:
        state = "STRONG"
        allowed = False
        reason = "dxy_above_sma30"
        drop_min = _nonnegative_float_param(merged.get("usd_strong_drop_min_pct"), 0.45)
        require_bearish = _bool_param(merged.get("usd_strong_drop_require_bearish_close"), True)
        bearish_ok = latest < latest_open if require_bearish else True
        if (
            _bool_param(merged.get("usd_strong_drop_override_enabled"), True)
            and slope_pct is not None
            and slope_pct <= -drop_min
            and bearish_ok
        ):
            state = "WEAK"
            allowed = True
            override = True
            reason = "dxy_above_sma30_but_falling_strongly"

    return DollarStrengthRead(
        symbol=DXY_SYMBOL,
        dxy_value=round(latest, 5),
        sma30=round(sma, 5),
        difference=round(difference, 5),
        state=state,  # type: ignore[arg-type]
        trading_allowed=allowed,
        reason=reason,
        slope_days=slope_days,
        slope_pct=round(slope_pct, 5) if slope_pct is not None else None,
        strong_drop_override_active=override,
        source="synthetic_mt5",
        updated_at=now,
        valid_until=valid_until,
        missing_symbols=missing,
        symbols_used=symbols_used,
        error_message=error_message,
        stale=bool(error_message),
    )


def usd_strength_decision_for_symbol(symbol: str, params: dict[str, object] | None, snapshot: DollarStrengthRead | None) -> DollarStrengthDecision:
    merged = merged_usd_strength_params(params)
    enabled = _bool_param(merged.get("usd_strength_filter_enabled"), True)
    applied_symbols = {str(item).upper() for item in _list_param(merged.get("usd_strength_apply_to_symbols"))}
    normalized_symbol = symbol.upper()
    read = snapshot or unknown_snapshot_read()
    metadata = dollar_strength_metadata(read)

    if not enabled:
        return DollarStrengthDecision(False, True, "usd_strength_filter_disabled", metadata)
    if normalized_symbol not in applied_symbols:
        return DollarStrengthDecision(True, True, "usd_strength_symbol_not_filtered", metadata)
    if read.trading_allowed:
        return DollarStrengthDecision(True, True, read.reason, metadata)
    return DollarStrengthDecision(True, False, "usd_strength_blocked", metadata)


def dollar_strength_metadata(read: DollarStrengthRead) -> dict[str, object]:
    return {
        "usd_strength_state": read.state,
        "usd_strength_trading_allowed": read.trading_allowed,
        "usd_strength_reason": read.reason,
        "dxy_value": read.dxy_value,
        "dxy_sma30": read.sma30,
        "dxy_difference": read.difference,
        "dxy_slope_pct": read.slope_pct,
        "strong_drop_override_active": read.strong_drop_override_active,
        "dxy_updated_at": read.updated_at.isoformat() if read.updated_at else None,
        "dxy_missing_symbols": read.missing_symbols,
    }


def unknown_snapshot_read() -> DollarStrengthRead:
    return DollarStrengthRead(updated_at=None, trading_allowed=True, missing_symbols=[symbol for symbol, _ in DXY_COMPONENTS])


def merged_usd_strength_params(params: dict[str, object] | None = None) -> dict[str, object]:
    return {**DEFAULT_USD_STRENGTH_PARAMS, **(params or {})}


def _candle_payload(row: Candle) -> dict[str, object]:
    return {"time": row.time, "open": row.open, "high": row.high, "low": row.low, "close": row.close}


def _ensure_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _positive_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bool_param(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "si"}
    return fallback


def _int_param(value: object, fallback: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return fallback
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _nonnegative_float_param(value: object, fallback: float) -> float:
    try:
        if value is None or isinstance(value, bool):
            return fallback
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _list_param(value: object) -> Iterable[object]:
    return value if isinstance(value, list) else DEFAULT_USD_STRENGTH_PARAMS["usd_strength_apply_to_symbols"]  # type: ignore[return-value]

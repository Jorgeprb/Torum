from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.core.config import get_settings
from app.drawings.models import ChartDrawing
from app.news.service import get_global_news_settings
from app.no_trade_zones.service import NoTradeZoneService
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings

TORUM_V1_KEY = "torum_v1"
MADRID_TZ = ZoneInfo("Europe/Madrid")
DEFAULT_BROKER_TZ = ZoneInfo("Etc/GMT-3")
SUPPORTED_SYMBOLS = ("XAUEUR", "XAUUSD")
SUPPORTED_EVALUATION_TIMEFRAMES = ("H2", "H3")


DEFAULT_TORUM_V1_PARAMS: dict[str, object] = {
    "use_news": True,
    "enable_operation_zones": True,
    "entry_timeframe": "M5",
    "pullback_enabled": True,
    "pullback_max_count": 10,
    "pullback_min_pct": 0.0,
    "pullback_threshold_pct": 0.0,
    "pullback_entry_min_pct": 0.20,
    "pullback_lookback_bars": 12,
    "pullback_swing_confirm_bars": 1,
    "pullback_allow_peak_extension": True,
    "pullback_require_bearish_leg": True,
    "pullback_min_bearish_candles": 1,
    "pullback_min_lower_close_candles": 1,
    "pullback_disallow_same_candle_peak_low": True,
    "pullback_impulse_green_filter_enabled": True,
    "pullback_recovery_pct": 0.10,
    "pullback_entry_recovery_pct": 0.0,
    "pullback_end_confirmation_bars": 1,
    "pullback_min_bars_between": 0,
    "pullback_use_wicks": True,
    "pullback_use_close_confirmation": True,
    "pullback_live_update_enabled": True,
    "pullback_live_anchor_to_low": True,
    "pullback_show_labels": True,
    "pullback_show_only_live": False,
    "pullback_label_decimals": 2,
    "pullback_line_width": 2,
    "pullback_opacity": 0.95,
    "show_pullback_debug": False,
    "require_zone": True,
    "operation_zone_allow_confirmation_price_outside": False,
    "one_position_per_symbol": False,
    "ath_green_prefer_x2_entries": True,
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
    "assets": {
        "XAUEUR": {
            "enabled": True,
            "timeframe": "H2",
            "session_start": "09:00",
            "session_end": "15:00",
        },
        "XAUUSD": {
            "enabled": True,
            "timeframe": "H2",
            "session_start": "15:30",
            "session_end": "21:00",
        },
    },
}

_LIVE_PULLBACK_LOW_CACHE: dict[str, "TorumV1Pullback"] = {}


@dataclass(frozen=True, slots=True)
class AggregatedCandle:
    start_time: datetime
    end_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class TorumV1Pullback:
    swing_high_time: datetime
    swing_high: float
    pullback_low_time: datetime
    pullback_low: float
    pullback_pct: float
    is_live: bool = False
    confirmation_candle_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class TorumV1OperationZone:
    drawing_id: str
    drawing_type: str
    time1: int
    time2: int | None
    price_min: float
    price_max: float
    direction: str = "BUY"


@dataclass(frozen=True, slots=True)
class TorumV1SupportZone:
    drawing_id: str
    level: int
    price: float
    lower_price: float
    upper_price: float
    opacity: float
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class TorumV1BuyDecision:
    should_buy: bool
    reason: str
    confirmation_candle_time: datetime | None = None
    pullback: TorumV1Pullback | None = None
    zone: TorumV1OperationZone | None = None
    support: TorumV1SupportZone | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TorumV1AssetStatus:
    symbol: str
    enabled: bool
    status: str
    reason: str
    timeframe: str
    session_start: str
    session_end: str
    unlocked_at: datetime | None
    blocked_by_news: bool
    active_config_id: int | None


@dataclass(frozen=True, slots=True)
class TorumV1Status:
    strategy_key: str
    enabled: bool
    use_news: bool
    server_time: datetime
    madrid_time: datetime
    assets: dict[str, TorumV1AssetStatus]


def detect_pullbacks(
    candles_m5: list[object],
    threshold: float = 0.20,
    lookback: int = 12,
    recovery_pct: float = 0.10,
    end_confirmation_bars: int = 1,
    *,
    max_count: int | None = None,
    min_bars_between: int = 0,
    use_wicks: bool = True,
    use_close_confirmation: bool = True,
    accept_doji_as_recovery: bool = False,
    live_update_enabled: bool = True,
    live_price: float | None = None,
    live_time: datetime | None = None,
    live_anchor_to_low: bool = True,
    live_cache_key: str | None = None,
    swing_confirm_bars: int = 1,
    allow_peak_extension: bool = True,
    require_bearish_leg: bool = True,
    min_bearish_candles: int = 1,
    min_lower_close_candles: int = 1,
    disallow_same_candle_peak_low: bool = True,
    impulse_green_filter_enabled: bool = True,
) -> list[TorumV1Pullback]:
    candles = _sorted_candles(candles_m5)
    if not candles:
        return []

    safe_threshold = max(0.0, float(threshold))
    safe_lookback = max(1, int(lookback))
    safe_recovery_pct = max(0.0, float(recovery_pct))
    required_recovery_bars = max(1, int(end_confirmation_bars))
    safe_swing_confirm_bars = max(0, int(swing_confirm_bars))
    safe_min_bars_between = max(0, int(min_bars_between))
    safe_min_bearish_candles = max(0, int(min_bearish_candles))
    safe_min_lower_close_candles = max(0, int(min_lower_close_candles))
    pullbacks: list[TorumV1Pullback] = []
    peak = candles[0]
    active: TorumV1Pullback | None = None
    confirmed_recovery_bars = 0
    bars_until_next_pullback = 0
    segment_start_index = 0

    for index, candle in enumerate(candles):
        high = float(candle.high)
        low = _pullback_low_source(candle, use_wicks)

        if active is None:
            if bars_until_next_pullback > 0:
                bars_until_next_pullback -= 1
                continue

            peak_index = _highest_high_index(candles, max(segment_start_index, index - safe_lookback + 1), index)
            peak = candles[peak_index]
            if index - peak_index < safe_swing_confirm_bars and index < len(candles) - 1:
                continue

            active = _pullback_from_peak_window(
                candles,
                peak_index,
                index,
                threshold=safe_threshold,
                use_wicks=use_wicks,
                require_bearish_leg=require_bearish_leg,
                min_bearish_candles=safe_min_bearish_candles,
                min_lower_close_candles=safe_min_lower_close_candles,
                disallow_same_candle_peak_low=disallow_same_candle_peak_low,
                impulse_green_filter_enabled=impulse_green_filter_enabled,
            )
            if active is None:
                continue
            # The candle that first reaches the qualifying low may also be the
            # reversal candle. Once it closes bullish (or as an accepted doji)
            # it is a valid confirmation and the market order is sent after its
            # close, i.e. at the beginning of the following M5 candle.
            confirmed_recovery_bars = 0

        if _as_utc(candle.time) < active.swing_high_time:
            continue

        if low < active.pullback_low:
            active = _updated_pullback_low(active, candle.time, low)
            confirmed_recovery_bars = 0
            # Do not skip the close of this candle: it can mark a fresh low and
            # still reject that low strongly enough to close bullish.

        recovered = float(candle.close) >= active.pullback_low * (1 + safe_recovery_pct / 100)
        if use_close_confirmation:
            recovered = recovered and (
                float(candle.close) >= float(candle.open)
                if accept_doji_as_recovery
                else float(candle.close) > float(candle.open)
            )
        confirmed_recovery_bars = confirmed_recovery_bars + 1 if recovered else 0
        if confirmed_recovery_bars >= required_recovery_bars:
            pullbacks.append(replace(active, confirmation_candle_time=_as_utc(candle.time)))
            peak = candle
            active = None
            confirmed_recovery_bars = 0
            bars_until_next_pullback = safe_min_bars_between
            segment_start_index = index
            continue

        if allow_peak_extension:
            active_peak_index = _index_for_time(candles, active.swing_high_time, fallback=index)
            candidate_peak_index = _highest_high_index(
                candles,
                max(segment_start_index, active_peak_index, index - safe_lookback + 1),
                index,
            )
            if candidate_peak_index == index:
                continue
            candidate_peak = candles[candidate_peak_index]
            candidate_peak_time = _as_utc(candidate_peak.time)
            if candidate_peak_time > active.swing_high_time and float(candidate_peak.high) > active.swing_high:
                updated = _pullback_from_peak_window(
                    candles,
                    candidate_peak_index,
                    index,
                    threshold=safe_threshold,
                    use_wicks=use_wicks,
                    require_bearish_leg=require_bearish_leg,
                    min_bearish_candles=safe_min_bearish_candles,
                    min_lower_close_candles=safe_min_lower_close_candles,
                    disallow_same_candle_peak_low=disallow_same_candle_peak_low,
                    impulse_green_filter_enabled=impulse_green_filter_enabled,
                )
                if updated is not None:
                    active = updated
                    confirmed_recovery_bars = 0
                    continue

    active = (
        _apply_live_pullback_update(
            active=active,
            candles=candles,
            peak=peak,
            last_candle=candles[-1],
            live_price=live_price,
            live_time=live_time,
            live_anchor_to_low=live_anchor_to_low,
            live_cache_key=live_cache_key,
            threshold=safe_threshold,
            use_wicks=use_wicks,
            require_bearish_leg=require_bearish_leg,
            min_bearish_candles=safe_min_bearish_candles,
            min_lower_close_candles=safe_min_lower_close_candles,
            disallow_same_candle_peak_low=disallow_same_candle_peak_low,
            impulse_green_filter_enabled=impulse_green_filter_enabled,
        )
        if live_update_enabled
        else active
    )
    if active is not None:
        pullbacks.append(replace(active, is_live=True))

    return _latest_pullbacks(pullbacks, max_count=max_count)


def _highest_high_index(candles: list[object], start: int, end: int) -> int:
    safe_start = max(0, start)
    safe_end = min(len(candles) - 1, end)
    best_index = safe_start
    best_high = float(candles[best_index].high)
    for index in range(safe_start + 1, safe_end + 1):
        high = float(candles[index].high)
        if high > best_high:
            best_high = high
            best_index = index
    return best_index


def _lowest_pullback_index(candles: list[object], start: int, end: int, use_wicks: bool) -> int:
    safe_start = max(0, start)
    safe_end = min(len(candles) - 1, end)
    best_index = safe_start
    best_low = _pullback_low_source(candles[best_index], use_wicks)
    for index in range(safe_start + 1, safe_end + 1):
        low = _pullback_low_source(candles[index], use_wicks)
        if low <= best_low:
            best_low = low
            best_index = index
    return best_index


def _index_for_time(candles: list[object], target_time: datetime, fallback: int = 0) -> int:
    target = _as_utc(target_time)
    for index, candle in enumerate(candles):
        if _as_utc(candle.time) == target:
            return index
    return max(0, min(len(candles) - 1, fallback))


def _pullback_from_peak_window(
    candles: list[object],
    peak_index: int,
    end_index: int,
    *,
    threshold: float,
    use_wicks: bool,
    require_bearish_leg: bool,
    min_bearish_candles: int,
    min_lower_close_candles: int,
    disallow_same_candle_peak_low: bool,
    impulse_green_filter_enabled: bool,
) -> TorumV1Pullback | None:
    if peak_index > end_index:
        return None
    peak = candles[peak_index]
    swing_high = float(peak.high)
    if swing_high <= 0:
        return None
    low_start_index = peak_index + 1 if disallow_same_candle_peak_low else (peak_index + 1 if peak_index < end_index else peak_index)
    if low_start_index > end_index:
        return None
    low_index = _lowest_pullback_index(candles, low_start_index, end_index, use_wicks)
    if disallow_same_candle_peak_low and low_index <= peak_index:
        return None
    leg_start = peak_index + 1
    has_bearish_leg = _has_bearish_leg(
        candles,
        leg_start,
        low_index,
        min_bearish_candles=min_bearish_candles,
        min_lower_close_candles=min_lower_close_candles,
    )
    if require_bearish_leg and not has_bearish_leg:
        return None
    low_candle = candles[low_index]
    if impulse_green_filter_enabled and _is_bullish_candle(low_candle) and not has_bearish_leg:
        return None
    low = _pullback_low_source(low_candle, use_wicks)
    if low >= swing_high:
        return None
    pullback_pct = _pullback_pct(swing_high, low)
    if pullback_pct < threshold:
        return None
    return TorumV1Pullback(
        swing_high_time=_as_utc(peak.time),
        swing_high=swing_high,
        pullback_low_time=_as_utc(low_candle.time),
        pullback_low=low,
        pullback_pct=pullback_pct,
    )


def _pullback_pct(swing_high: float, pullback_low: float) -> float:
    return (swing_high - pullback_low) / swing_high * 100 if swing_high > 0 else 0.0


def _pullback_low_source(candle: object, use_wicks: bool) -> float:
    if use_wicks:
        return float(candle.low)
    return float(candle.close)


def _is_bullish_candle(candle: object) -> bool:
    return float(candle.close) > float(candle.open)


def _bearish_leg_counts(candles: list[object], start_index: int, low_index: int) -> tuple[int, int]:
    safe_start = max(0, start_index)
    safe_end = min(len(candles) - 1, low_index)
    if safe_start > safe_end:
        return 0, 0

    bearish = 0
    lower_close = 0
    for index in range(safe_start, safe_end + 1):
        candle = candles[index]
        previous = candles[index - 1] if index > 0 else None
        if float(candle.close) < float(candle.open):
            bearish += 1
        if previous is not None and float(candle.close) < float(previous.close):
            lower_close += 1
    return bearish, lower_close


def _has_bearish_leg(
    candles: list[object],
    start_index: int,
    low_index: int,
    *,
    min_bearish_candles: int,
    min_lower_close_candles: int,
) -> bool:
    if min_bearish_candles <= 0 and min_lower_close_candles <= 0:
        return True
    bearish, lower_close = _bearish_leg_counts(candles, start_index, low_index)
    return (min_bearish_candles > 0 and bearish >= min_bearish_candles) or (
        min_lower_close_candles > 0 and lower_close >= min_lower_close_candles
    )


def _latest_pullbacks(pullbacks: list[TorumV1Pullback], max_count: int | None) -> list[TorumV1Pullback]:
    ordered = sorted(pullbacks, key=lambda pullback: pullback.swing_high_time)
    if max_count is None:
        return ordered
    safe_max = max(0, int(max_count))
    if safe_max == 0:
        return []
    return ordered[-safe_max:]


def _updated_pullback_low(pullback: TorumV1Pullback, low_time: datetime, low: float) -> TorumV1Pullback:
    return TorumV1Pullback(
        swing_high_time=pullback.swing_high_time,
        swing_high=pullback.swing_high,
        pullback_low_time=_as_utc(low_time),
        pullback_low=low,
        pullback_pct=_pullback_pct(pullback.swing_high, low),
        confirmation_candle_time=None,
    )


def _apply_live_pullback_update(
    *,
    active: TorumV1Pullback | None,
    candles: list[object],
    peak: object,
    last_candle: object,
    live_price: float | None,
    live_time: datetime | None,
    live_anchor_to_low: bool,
    live_cache_key: str | None,
    threshold: float,
    use_wicks: bool,
    require_bearish_leg: bool,
    min_bearish_candles: int,
    min_lower_close_candles: int,
    disallow_same_candle_peak_low: bool,
    impulse_green_filter_enabled: bool,
) -> TorumV1Pullback | None:
    if live_price is None:
        return active

    del impulse_green_filter_enabled
    live_low, low_time = _live_low_candidate(
        last_candle=last_candle,
        live_price=live_price,
        live_time=live_time,
        use_wicks=use_wicks,
        anchor_to_low=live_anchor_to_low,
    )

    effective_cache_key = live_cache_key if live_anchor_to_low else None
    cached = _cached_live_pullback(effective_cache_key, peak)
    if cached is not None and cached.pullback_pct >= threshold and (active is None or cached.pullback_low < active.pullback_low):
        active = cached

    if active is not None:
        if live_low < active.pullback_low:
            updated = _updated_pullback_low(active, low_time, live_low)
            _store_live_pullback(effective_cache_key, updated)
            return updated
        _store_live_pullback(effective_cache_key, active)
        return active

    swing_high = float(peak.high)
    if swing_high <= 0 or live_low >= swing_high:
        return None
    peak_index = _index_for_time(candles, _as_utc(peak.time), fallback=len(candles) - 1)
    if disallow_same_candle_peak_low and peak_index >= len(candles) - 1:
        return None
    if require_bearish_leg and not _has_bearish_leg(
        candles,
        peak_index + 1,
        len(candles) - 1,
        min_bearish_candles=min_bearish_candles,
        min_lower_close_candles=min_lower_close_candles,
    ):
        return None
    if low_time <= _as_utc(peak.time):
        return None

    pullback_pct = _pullback_pct(swing_high, live_low)
    if pullback_pct < threshold:
        return None

    pullback = TorumV1Pullback(
        swing_high_time=_as_utc(peak.time),
        swing_high=swing_high,
        pullback_low_time=low_time,
        pullback_low=live_low,
        pullback_pct=pullback_pct,
    )
    _store_live_pullback(effective_cache_key, pullback)
    return pullback


def _cached_live_pullback(cache_key: str | None, peak: object) -> TorumV1Pullback | None:
    if not cache_key:
        return None
    cached = _LIVE_PULLBACK_LOW_CACHE.get(cache_key)
    if cached is None:
        return None
    if cached.swing_high_time == _as_utc(peak.time) and abs(cached.swing_high - float(peak.high)) < 0.0000001:
        return cached
    _LIVE_PULLBACK_LOW_CACHE.pop(cache_key, None)
    return None


def _store_live_pullback(cache_key: str | None, pullback: TorumV1Pullback) -> None:
    if not cache_key:
        return
    _LIVE_PULLBACK_LOW_CACHE[cache_key] = replace(pullback, is_live=False)


def _live_low_candidate(
    *,
    last_candle: object,
    live_price: float,
    live_time: datetime | None,
    use_wicks: bool,
    anchor_to_low: bool,
) -> tuple[float, datetime]:
    live = float(live_price)
    live_timestamp = _as_utc(live_time or datetime.now(UTC))
    if not anchor_to_low:
        return live, live_timestamp
    if not use_wicks:
        return live, live_timestamp

    candle_low = float(last_candle.low)
    if candle_low <= live:
        return candle_low, _as_utc(last_candle.time)
    return live, live_timestamp


def is_bullish_confirmation(candle: object, *, accept_doji_as_bullish: bool = False) -> bool:
    close = float(candle.close)
    open_price = float(candle.open)
    return close >= open_price if accept_doji_as_bullish else close > open_price


def operation_zones_from_drawings(drawings: list[ChartDrawing]) -> list[TorumV1OperationZone]:
    zones: list[TorumV1OperationZone] = []
    for drawing in drawings:
        if drawing.drawing_type not in {"rectangle", "manual_zone"}:
            continue
        payload = drawing.payload_json or {}
        metadata = drawing.metadata_json or {}
        if not _bool(metadata.get("torum_v1_zone_enabled", payload.get("torum_v1_zone_enabled")), False):
            continue

        zone = _operation_zone_from_payload(drawing.id, drawing.drawing_type, payload, metadata)
        if zone is not None:
            zones.append(zone)
    return zones


def support_zones_from_drawings(drawings: list[ChartDrawing]) -> list[TorumV1SupportZone]:
    zones: list[TorumV1SupportZone] = []
    for drawing in drawings:
        if drawing.drawing_type != "horizontal_line":
            continue
        payload = drawing.payload_json or {}
        metadata = drawing.metadata_json or {}
        style = drawing.style_json or {}
        support = metadata.get("support") if isinstance(metadata.get("support"), dict) else metadata
        level = _support_level(support.get("supportLevel"))
        enabled = _bool(support.get("enabled"), True)
        price = _float_or_none(payload.get("price"))
        if level is None or price is None or not enabled:
            continue
        lower = _float_or_none(support.get("supportLowerPrice"))
        upper = _float_or_none(support.get("supportUpperPrice"))
        if lower is None or upper is None:
            width = max(price * 0.0005, 0.5)
            lower = price - width
            upper = price + width
        opacity = _float_or_none(support.get("opacity"))
        if opacity is None:
            opacity = _float_or_none(style.get("supportOpacity")) or 0.20
        zones.append(
            TorumV1SupportZone(
                drawing_id=drawing.id,
                level=level,
                price=price,
                lower_price=min(lower, upper),
                upper_price=max(lower, upper),
                opacity=max(0.0, min(1.0, opacity)),
                enabled=enabled,
            )
        )
    return zones


def is_candle_inside_operation_zone(
    candle: object,
    zone: TorumV1OperationZone,
    timeframe_seconds: int = 300,
    *,
    price: float | None = None,
    price_tolerance_pct: float = 0.0,
    time_tolerance_minutes: int = 0,
) -> bool:
    """Return whether the executable confirmation point is inside the rectangle.

    The strategy acts only after the M5 candle has closed, so the temporal point
    is the candle close and the vertical point is the executable price when it
    is available (otherwise the candle close). Keeping both coordinates in the
    same helper prevents a rectangle from being treated as a time-only filter.
    """

    candle_close_time = _as_utc(candle.time) + timedelta(seconds=max(0, int(timeframe_seconds)))
    checked_price = float(candle.close) if price is None else float(price)
    return is_price_time_inside_operation_zone(
        checked_at=candle_close_time,
        price=checked_price,
        zone=zone,
        price_tolerance_pct=price_tolerance_pct,
        time_tolerance_minutes=time_tolerance_minutes,
    )


def is_pullback_low_inside_operation_zone(
    pullback: TorumV1Pullback,
    zone: TorumV1OperationZone,
    timeframe_seconds: int = 300,
    *,
    price_tolerance_pct: float = 0.0,
    time_tolerance_minutes: int = 0,
) -> bool:
    del timeframe_seconds
    return is_price_time_inside_operation_zone(
        checked_at=_as_utc(pullback.pullback_low_time),
        price=float(pullback.pullback_low),
        zone=zone,
        price_tolerance_pct=price_tolerance_pct,
        time_tolerance_minutes=time_tolerance_minutes,
    )


def is_time_inside_operation_zone(
    *,
    checked_at: datetime,
    zone: TorumV1OperationZone,
    time_tolerance_minutes: int = 0,
) -> bool:
    """Validate only the horizontal/time coordinate of a point."""

    checked_time = int(_as_utc(checked_at).timestamp())
    time_tolerance = max(0, int(time_tolerance_minutes)) * 60
    if checked_time < zone.time1 - time_tolerance:
        return False
    return zone.time2 is None or checked_time <= zone.time2 + time_tolerance


def is_price_inside_operation_zone(
    *,
    price: float,
    zone: TorumV1OperationZone,
    price_tolerance_pct: float = 0.0,
) -> bool:
    """Validate only the vertical/price coordinate of a point."""

    checked_price = float(price)
    price_tolerance = max(0.0, float(price_tolerance_pct)) / 100.0
    center = (zone.price_min + zone.price_max) / 2.0
    absolute_price_tolerance = abs(center) * price_tolerance
    return zone.price_min - absolute_price_tolerance <= checked_price <= zone.price_max + absolute_price_tolerance


def is_price_time_inside_operation_zone(
    *,
    checked_at: datetime,
    price: float,
    zone: TorumV1OperationZone,
    price_tolerance_pct: float = 0.0,
    time_tolerance_minutes: int = 0,
) -> bool:
    """Validate both coordinates of an entry/pullback point against a zone."""

    return is_time_inside_operation_zone(
        checked_at=checked_at,
        zone=zone,
        time_tolerance_minutes=time_tolerance_minutes,
    ) and is_price_inside_operation_zone(
        price=price,
        zone=zone,
        price_tolerance_pct=price_tolerance_pct,
    )


def _executed_entry_cycle_boundaries(params: dict[str, Any]) -> list[int]:
    """Return successful-entry confirmation times used to reset pullback cycles."""

    raw_values = params.get("executed_entry_cycle_boundaries")
    values: list[object] = list(raw_values) if isinstance(raw_values, (list, tuple, set)) else []
    values.append(params.get("last_executed_entry_candle_time"))
    boundaries = {
        parsed
        for value in values
        if (parsed := _int_or_none(value)) is not None and parsed > 0
    }
    return sorted(boundaries)


def _current_pullback_cycle_candles(
    candles: list[object],
    params: dict[str, Any],
) -> list[object]:
    """Keep only candles belonging to the setup cycle after the latest entry.

    The confirmation candle is deliberately included again as the first anchor
    of the new cycle. The executed trade is opened after that candle closes, so
    the following candle can establish a new swing high and a later decline can
    form an entirely new pullback.
    """

    ordered = _sorted_candles(candles)
    boundaries = _executed_entry_cycle_boundaries(params)
    if not ordered or not boundaries:
        return ordered
    boundary = datetime.fromtimestamp(boundaries[-1], UTC)
    return [candle for candle in ordered if _as_utc(candle.time) >= boundary]


def _pullback_cycle_segments(
    candles: list[object],
    params: dict[str, Any],
) -> list[list[object]]:
    """Split chart history at successful entries while sharing the boundary bar.

    Sharing the entry-confirmation candle lets it finish the old pullback and
    become the initial anchor of the next cycle. This keeps completed pullbacks
    visible while preventing a post-entry fall from extending the old setup.
    """

    ordered = _sorted_candles(candles)
    if not ordered:
        return []

    first_time = _as_utc(ordered[0].time)
    last_time = _as_utc(ordered[-1].time)
    boundaries = [
        datetime.fromtimestamp(value, UTC)
        for value in _executed_entry_cycle_boundaries(params)
        if first_time <= datetime.fromtimestamp(value, UTC) <= last_time
    ]
    if not boundaries:
        return [ordered]

    segments: list[list[object]] = []
    start_index = 0
    for boundary in boundaries:
        boundary_index = next(
            (index for index, candle in enumerate(ordered) if _as_utc(candle.time) >= boundary),
            len(ordered) - 1,
        )
        if boundary_index < start_index:
            continue
        segment = ordered[start_index : boundary_index + 1]
        if segment:
            segments.append(segment)
        start_index = boundary_index

    tail = ordered[start_index:]
    if tail:
        segments.append(tail)
    return segments


def should_buy_torum_v1(
    *,
    symbol: str,
    candles_m5: list[object],
    operation_zones: list[TorumV1OperationZone],
    support_zones: list[TorumV1SupportZone] | None = None,
    params: dict[str, Any],
    now: datetime | None = None,
    open_positions: list[object] | None = None,
    current_price: float | None = None,
) -> TorumV1BuyDecision:
    if not _bool(params.get("enabled"), True):
        return TorumV1BuyDecision(False, "strategy_disabled")

    if _bool(params.get("one_position_per_symbol"), True) and open_positions:
        return TorumV1BuyDecision(False, "open_position_exists")

    checked_at = _as_utc(now or datetime.now(UTC))
    closed = _closed_entry_candles(candles_m5, checked_at)
    if len(closed) < 2:
        return TorumV1BuyDecision(False, "missing_closed_m5_candles")

    confirmation = closed[-1]
    confirmation_time = _as_utc(confirmation.time)
    confirmation_time_int = int(confirmation_time.timestamp())
    last_signal_time = _int_or_none(params.get("last_signal_candle_time"))
    if last_signal_time == confirmation_time_int:
        return TorumV1BuyDecision(False, "duplicate_signal_candle")

    confirmation_bars_required = max(1, _int_param(params.get("confirmation_bars"), 1))
    recent_confirmation = closed[-confirmation_bars_required:]
    if len(recent_confirmation) < confirmation_bars_required:
        return TorumV1BuyDecision(False, "missing_confirmation_bars")
    accept_doji_as_bullish = _bool(params.get("confirmation_ignore_doji"), True)
    if _bool(params.get("confirmation_require_bullish"), True) and not all(
        is_bullish_confirmation(item, accept_doji_as_bullish=accept_doji_as_bullish)
        for item in recent_confirmation
    ):
        return TorumV1BuyDecision(False, "waiting_bullish_confirmation")
    min_body_pct = _nonnegative_float_param(params.get("confirmation_min_body_pct"), 0.0)
    if min_body_pct > 0:
        for item in recent_confirmation:
            item_open = float(item.open)
            if item_open <= 0 or abs(float(item.close) - item_open) / item_open * 100.0 < min_body_pct:
                return TorumV1BuyDecision(False, "confirmation_body_too_small")
    if _bool(params.get("confirmation_close_above_previous_high"), False):
        confirmation_index = len(closed) - confirmation_bars_required
        if confirmation_index <= 0 or float(recent_confirmation[-1].close) <= float(closed[confirmation_index - 1].high):
            return TorumV1BuyDecision(False, "confirmation_below_previous_high")

    if not _bool(params.get("pullback_enabled"), True):
        return TorumV1BuyDecision(False, "pullback_disabled")

    entry_threshold = _pullback_entry_threshold(params)
    if entry_threshold <= 0:
        return TorumV1BuyDecision(False, "missing_pullback_entry_min_pct")

    detector_closed = _current_pullback_cycle_candles(closed, params)
    # The entry detector must not segment sub-threshold corrections.  Starting
    # it at 0.0 allowed small recoveries to close a setup before the accumulated
    # decline reached the configured entry minimum.  Detect qualifying entries
    # with the real threshold and keep the visual recovery percentage separate
    # from the optional recovery required for an automatic entry.
    detection_threshold = entry_threshold
    entry_recovery_pct = _nonnegative_float_param(params.get("pullback_entry_recovery_pct"), 0.0)
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    confirmation_bars = _int_param(params.get("pullback_end_confirmation_bars"), 1)
    min_bars_between = _nonnegative_int_param(params.get("pullback_min_bars_between"), 0)
    swing_confirm_bars = _nonnegative_int_param(params.get("pullback_swing_confirm_bars"), 1)
    allow_peak_extension = _bool(params.get("pullback_allow_peak_extension"), True)
    require_bearish_leg = _bool(params.get("pullback_require_bearish_leg"), True)
    min_bearish_candles = _nonnegative_int_param(params.get("pullback_min_bearish_candles"), 1)
    min_lower_close_candles = _nonnegative_int_param(params.get("pullback_min_lower_close_candles"), 1)
    disallow_same_candle_peak_low = _bool(params.get("pullback_disallow_same_candle_peak_low"), True)
    impulse_green_filter_enabled = _bool(params.get("pullback_impulse_green_filter_enabled"), True)
    pullbacks = [
        pullback
        for pullback in detect_pullbacks(
            detector_closed,
            detection_threshold,
            lookback,
            entry_recovery_pct,
            confirmation_bars,
            max_count=_int_param(params.get("pullback_max_count"), 10),
            min_bars_between=min_bars_between,
            use_wicks=_bool(params.get("pullback_use_wicks"), True),
            use_close_confirmation=_bool(params.get("pullback_use_close_confirmation"), True),
            accept_doji_as_recovery=accept_doji_as_bullish,
            live_update_enabled=False,
            live_anchor_to_low=_bool(params.get("pullback_live_anchor_to_low"), True),
            swing_confirm_bars=swing_confirm_bars,
            allow_peak_extension=allow_peak_extension,
            require_bearish_leg=require_bearish_leg,
            min_bearish_candles=min_bearish_candles,
            min_lower_close_candles=min_lower_close_candles,
            disallow_same_candle_peak_low=disallow_same_candle_peak_low,
            impulse_green_filter_enabled=impulse_green_filter_enabled,
        )
        if not pullback.is_live
        and pullback.pullback_low_time <= confirmation_time
        and pullback.confirmation_candle_time == confirmation_time
    ]
    if not pullbacks:
        # Run a threshold-free diagnostic pass only to explain whether the
        # current candle confirmed a smaller correction.  This pass never
        # authorizes an order, so an old qualifying pullback cannot be reused.
        diagnostic_pullbacks = [
            pullback
            for pullback in detect_pullbacks(
                detector_closed,
                0.0,
                lookback,
                entry_recovery_pct,
                confirmation_bars,
                max_count=_int_param(params.get("pullback_max_count"), 10),
                min_bars_between=min_bars_between,
                use_wicks=_bool(params.get("pullback_use_wicks"), True),
                use_close_confirmation=_bool(params.get("pullback_use_close_confirmation"), True),
                accept_doji_as_recovery=accept_doji_as_bullish,
                live_update_enabled=False,
                live_anchor_to_low=_bool(params.get("pullback_live_anchor_to_low"), True),
                swing_confirm_bars=swing_confirm_bars,
                allow_peak_extension=allow_peak_extension,
                require_bearish_leg=require_bearish_leg,
                min_bearish_candles=min_bearish_candles,
                min_lower_close_candles=min_lower_close_candles,
                disallow_same_candle_peak_low=disallow_same_candle_peak_low,
                impulse_green_filter_enabled=impulse_green_filter_enabled,
            )
            if not pullback.is_live
            and pullback.pullback_low_time <= confirmation_time
            and pullback.confirmation_candle_time == confirmation_time
        ]
        if diagnostic_pullbacks:
            diagnostic = max(
                diagnostic_pullbacks,
                key=lambda item: (item.pullback_low_time, item.swing_high_time, item.pullback_pct),
            )
            return TorumV1BuyDecision(
                False,
                "current_pullback_below_entry_min",
                confirmation_time,
                diagnostic,
                metadata={
                    "confirmation_candle_time": confirmation_time_int,
                    "pullback_confirmation_candle_time": int(diagnostic.confirmation_candle_time.timestamp())
                    if diagnostic.confirmation_candle_time is not None
                    else None,
                    "pullback_pct": diagnostic.pullback_pct,
                    "pullback_entry_min_pct": entry_threshold,
                    "pullback_entry_recovery_pct": entry_recovery_pct,
                    "swing_high": diagnostic.swing_high,
                    "swing_high_time": int(diagnostic.swing_high_time.timestamp()),
                    "pullback_low": diagnostic.pullback_low,
                    "pullback_low_time": int(diagnostic.pullback_low_time.timestamp()),
                },
            )
        return TorumV1BuyDecision(
            False,
            "missing_current_pullback",
            confirmation_time,
            metadata={
                "confirmation_candle_time": confirmation_time_int,
                "pullback_entry_min_pct": entry_threshold,
                "pullback_entry_recovery_pct": entry_recovery_pct,
            },
        )

    # There should be only one setup ending on a candle.  Sorting by the most
    # recent low and swing high keeps the choice deterministic if historical
    # data contains duplicated/overlapping candidates.
    pullback = max(
        pullbacks,
        key=lambda item: (item.pullback_low_time, item.swing_high_time, item.pullback_pct),
    )
    if pullback.pullback_pct < entry_threshold:
        return TorumV1BuyDecision(
            False,
            "current_pullback_below_entry_min",
            confirmation_time,
            pullback,
            metadata={
                "confirmation_candle_time": confirmation_time_int,
                "pullback_confirmation_candle_time": int(pullback.confirmation_candle_time.timestamp())
                if pullback.confirmation_candle_time is not None
                else None,
                "pullback_pct": pullback.pullback_pct,
                "pullback_entry_min_pct": entry_threshold,
                "swing_high": pullback.swing_high,
                "swing_high_time": int(pullback.swing_high_time.timestamp()),
                "pullback_low": pullback.pullback_low,
                "pullback_low_time": int(pullback.pullback_low_time.timestamp()),
            },
        )
    require_zone = _bool(params.get("require_zone"), True)
    zones_enabled = _bool(params.get("enable_operation_zones"), True)
    price_tolerance_pct = _nonnegative_float_param(params.get("operation_zone_price_tolerance_pct"), 0.0)
    time_tolerance_minutes = _nonnegative_int_param(params.get("operation_zone_time_tolerance_minutes"), 0)
    pullback_matching_zones: list[TorumV1OperationZone] = []
    if zones_enabled:
        pullback_matching_zones = [
            zone
            for zone in operation_zones
            if zone.direction == "BUY"
            and is_pullback_low_inside_operation_zone(
                pullback,
                zone,
                price_tolerance_pct=price_tolerance_pct,
                time_tolerance_minutes=time_tolerance_minutes,
            )
        ]

    if require_zone and not pullback_matching_zones:
        return TorumV1BuyDecision(False, "pullback_low_outside_operation_zone", confirmation_time, pullback)

    allow_confirmation_price_outside = _bool(
        params.get("operation_zone_allow_confirmation_price_outside"),
        False,
    )
    executable_price = float(current_price) if current_price is not None else float(confirmation.close)
    confirmation_close_at = confirmation_time + timedelta(minutes=5)
    confirmation_time_matching_zone = next(
        (
            zone
            for zone in pullback_matching_zones
            if is_time_inside_operation_zone(
                checked_at=confirmation_close_at,
                zone=zone,
                time_tolerance_minutes=time_tolerance_minutes,
            )
        ),
        None,
    )
    confirmation_matching_zone = next(
        (
            zone
            for zone in pullback_matching_zones
            if is_time_inside_operation_zone(
                checked_at=confirmation_close_at,
                zone=zone,
                time_tolerance_minutes=time_tolerance_minutes,
            )
            and is_price_inside_operation_zone(
                price=executable_price,
                zone=zone,
                price_tolerance_pct=price_tolerance_pct,
            )
        ),
        None,
    )
    pullback_zone = pullback_matching_zones[0] if pullback_matching_zones else None

    if require_zone and confirmation_time_matching_zone is None:
        zone_metadata = _operation_zone_decision_metadata(
            pullback_zone,
            confirmation=confirmation,
            executable_price=executable_price,
            confirmation_time_inside=False,
            confirmation_price_inside=False,
            allow_confirmation_price_outside=allow_confirmation_price_outside,
        )
        zone_metadata.update(
            {
                "confirmation_candle_time": confirmation_time_int,
                "pullback_pct": pullback.pullback_pct,
                "pullback_low": pullback.pullback_low,
                "pullback_low_time": int(pullback.pullback_low_time.timestamp()),
            }
        )
        return TorumV1BuyDecision(
            False,
            "confirmation_time_outside_operation_zone",
            confirmation_time,
            pullback,
            pullback_zone,
            metadata=zone_metadata,
        )

    if require_zone and not allow_confirmation_price_outside and confirmation_matching_zone is None:
        zone_metadata = _operation_zone_decision_metadata(
            confirmation_time_matching_zone,
            confirmation=confirmation,
            executable_price=executable_price,
            confirmation_time_inside=True,
            confirmation_price_inside=False,
            allow_confirmation_price_outside=False,
        )
        zone_metadata.update(
            {
                "confirmation_candle_time": confirmation_time_int,
                "pullback_pct": pullback.pullback_pct,
                "pullback_low": pullback.pullback_low,
                "pullback_low_time": int(pullback.pullback_low_time.timestamp()),
            }
        )
        return TorumV1BuyDecision(
            False,
            "confirmation_price_outside_operation_zone",
            confirmation_time,
            pullback,
            confirmation_time_matching_zone,
            metadata=zone_metadata,
        )

    matching_zone = confirmation_matching_zone or (
        confirmation_time_matching_zone if allow_confirmation_price_outside else None
    )
    if matching_zone is None and not require_zone:
        matching_zone = pullback_zone

    last_pullback_time = _int_or_none(params.get("last_signal_pullback_low_time"))
    pullback_low_time_int = int(pullback.pullback_low_time.timestamp())
    if last_pullback_time == pullback_low_time_int:
        return TorumV1BuyDecision(False, "duplicate_signal_pullback", confirmation_time, pullback, matching_zone)

    matching_support, support_reference_price, support_distance_pct = _matching_support_for_entry(
        pullback,
        support_zones or [],
        executable_price=executable_price,
        params=params,
    )
    desired_multiplier = desired_multiplier_for_support(
        matching_support.level if matching_support is not None else None,
        open_positions or [],
        params=params,
    )

    confirmation_time_inside_zone = confirmation_time_matching_zone is not None
    confirmation_price_inside_zone = confirmation_matching_zone is not None
    confirmation_inside_zone = confirmation_time_inside_zone and confirmation_price_inside_zone
    confirmation_price_outside_allowed = (
        matching_zone is not None
        and confirmation_time_inside_zone
        and not confirmation_price_inside_zone
        and allow_confirmation_price_outside
    )
    metadata = {
        "symbol": symbol.upper(),
        "entry_timeframe": "M5",
        "entry_setup": (
            "pullback_low_inside_zone_confirmation_price_outside_allowed"
            if confirmation_price_outside_allowed
            else "pullback_and_confirmation_inside_zone"
            if matching_zone is not None
            else "pullback_without_required_operation_zone"
        ),
        "confirmation_candle_time": confirmation_time_int,
        "confirmation_close_time": int(confirmation_close_at.timestamp()),
        "confirmation_close": float(confirmation.close),
        "executable_price": executable_price,
        "confirmation_time_inside_operation_zone": confirmation_time_inside_zone,
        "confirmation_price_inside_operation_zone": confirmation_price_inside_zone,
        "confirmation_inside_operation_zone": confirmation_inside_zone,
        "operation_zone_allow_confirmation_price_outside": allow_confirmation_price_outside,
        "pullback_pct": pullback.pullback_pct,
        "swing_high": pullback.swing_high,
        "swing_high_time": int(pullback.swing_high_time.timestamp()),
        "pullback_low": pullback.pullback_low,
        "pullback_low_time": pullback_low_time_int,
        "pullback_confirmation_candle_time": int(pullback.confirmation_candle_time.timestamp())
        if pullback.confirmation_candle_time is not None
        else None,
        "pullback_entry_min_pct": entry_threshold,
        "pullback_entry_recovery_pct": entry_recovery_pct,
        "operation_zone_id": matching_zone.drawing_id if matching_zone else None,
        "support_zone_id": matching_support.drawing_id if matching_support else None,
        "support_level": matching_support.level if matching_support else None,
        "support_reference": str(params.get("support_reference") or "PULLBACK_LOW").upper(),
        "support_reference_price": support_reference_price,
        "support_distance_pct": support_distance_pct,
        "desired_multiplier": desired_multiplier,
    }
    metadata.update(
        _operation_zone_decision_metadata(
            matching_zone,
            confirmation=confirmation,
            executable_price=executable_price,
            confirmation_time_inside=confirmation_time_inside_zone,
            confirmation_price_inside=confirmation_price_inside_zone,
            allow_confirmation_price_outside=allow_confirmation_price_outside,
        )
    )
    reason = (
        "buy_pullback_inside_zone_confirmation_price_outside_allowed"
        if confirmation_price_outside_allowed
        else "buy_pullback_confirmed_inside_zone"
    )
    return TorumV1BuyDecision(True, reason, confirmation_time, pullback, matching_zone, matching_support, metadata)


def torum_v1_diagnostic_snapshot(
    *,
    symbol: str,
    candles_m5: list[object],
    operation_zones: list[TorumV1OperationZone],
    support_zones: list[TorumV1SupportZone] | None,
    params: dict[str, Any],
    now: datetime | None = None,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Build a side-effect-free snapshot explaining the current entry setup.

    It intentionally runs both the real detector and a threshold-free detector.
    The latter never authorizes an entry; it only shows whether the latest
    bullish candle confirmed a smaller correction or whether a pullback remains
    live without confirmation.
    """

    checked_at = _as_utc(now or datetime.now(UTC))
    closed = _closed_entry_candles(candles_m5, checked_at)
    detector_closed = _current_pullback_cycle_candles(closed, params)
    entry_threshold = _pullback_entry_threshold(params)
    entry_recovery_pct = _nonnegative_float_param(params.get("pullback_entry_recovery_pct"), 0.0)
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    confirmation_bars = _int_param(params.get("pullback_end_confirmation_bars"), 1)
    min_bars_between = _nonnegative_int_param(params.get("pullback_min_bars_between"), 0)
    swing_confirm_bars = _nonnegative_int_param(params.get("pullback_swing_confirm_bars"), 1)
    accept_doji = _bool(params.get("confirmation_ignore_doji"), True)
    use_wicks = _bool(params.get("pullback_use_wicks"), True)
    use_close_confirmation = _bool(params.get("pullback_use_close_confirmation"), True)
    allow_peak_extension = _bool(params.get("pullback_allow_peak_extension"), True)
    require_bearish_leg = _bool(params.get("pullback_require_bearish_leg"), True)
    min_bearish_candles = _nonnegative_int_param(params.get("pullback_min_bearish_candles"), 1)
    min_lower_close_candles = _nonnegative_int_param(params.get("pullback_min_lower_close_candles"), 1)
    disallow_same_candle_peak_low = _bool(params.get("pullback_disallow_same_candle_peak_low"), True)
    impulse_green_filter_enabled = _bool(params.get("pullback_impulse_green_filter_enabled"), True)

    common_kwargs = {
        "lookback": lookback,
        "recovery_pct": entry_recovery_pct,
        "end_confirmation_bars": confirmation_bars,
        "max_count": 20,
        "min_bars_between": min_bars_between,
        "use_wicks": use_wicks,
        "use_close_confirmation": use_close_confirmation,
        "accept_doji_as_recovery": accept_doji,
        "live_update_enabled": False,
        "live_anchor_to_low": _bool(params.get("pullback_live_anchor_to_low"), True),
        "swing_confirm_bars": swing_confirm_bars,
        "allow_peak_extension": allow_peak_extension,
        "require_bearish_leg": require_bearish_leg,
        "min_bearish_candles": min_bearish_candles,
        "min_lower_close_candles": min_lower_close_candles,
        "disallow_same_candle_peak_low": disallow_same_candle_peak_low,
        "impulse_green_filter_enabled": impulse_green_filter_enabled,
    }
    qualifying = detect_pullbacks(detector_closed, threshold=entry_threshold, **common_kwargs) if detector_closed else []
    threshold_free = detect_pullbacks(detector_closed, threshold=0.0, **common_kwargs) if detector_closed else []

    confirmation = closed[-1] if closed else None
    confirmation_time = _as_utc(confirmation.time) if confirmation is not None else None
    confirmation_close_at = confirmation_time + timedelta(minutes=5) if confirmation_time is not None else None
    executable_price = (
        float(current_price)
        if current_price is not None
        else float(confirmation.close)
        if confirmation is not None
        else None
    )
    price_tolerance_pct = _nonnegative_float_param(params.get("operation_zone_price_tolerance_pct"), 0.0)
    time_tolerance_minutes = _nonnegative_int_param(params.get("operation_zone_time_tolerance_minutes"), 0)

    def pullback_payload(item: TorumV1Pullback) -> dict[str, Any]:
        zone_checks = []
        for zone in operation_zones:
            low_inside = is_pullback_low_inside_operation_zone(
                item,
                zone,
                price_tolerance_pct=price_tolerance_pct,
                time_tolerance_minutes=time_tolerance_minutes,
            )
            confirmation_time_inside = (
                is_time_inside_operation_zone(
                    checked_at=confirmation_close_at,
                    zone=zone,
                    time_tolerance_minutes=time_tolerance_minutes,
                )
                if confirmation_close_at is not None
                else False
            )
            confirmation_price_inside = (
                is_price_inside_operation_zone(
                    price=executable_price,
                    zone=zone,
                    price_tolerance_pct=price_tolerance_pct,
                )
                if executable_price is not None
                else False
            )
            zone_checks.append(
                {
                    "zone_id": zone.drawing_id,
                    "direction": zone.direction,
                    "time1": zone.time1,
                    "time2": zone.time2,
                    "price_min": zone.price_min,
                    "price_max": zone.price_max,
                    "pullback_low_inside": low_inside,
                    "confirmation_time_inside": confirmation_time_inside,
                    "confirmation_price_inside": confirmation_price_inside,
                }
            )
        support, support_reference_price, support_distance_pct = _matching_support_for_entry(
            item,
            support_zones or [],
            executable_price=executable_price if executable_price is not None else float(item.pullback_low),
            params=params,
        )
        return {
            "swing_high_time": item.swing_high_time,
            "swing_high": item.swing_high,
            "pullback_low_time": item.pullback_low_time,
            "pullback_low": item.pullback_low,
            "pullback_pct": item.pullback_pct,
            "is_live": item.is_live,
            "confirmation_candle_time": item.confirmation_candle_time,
            "confirms_latest_closed_candle": (
                item.confirmation_candle_time == confirmation_time
                if item.confirmation_candle_time is not None and confirmation_time is not None
                else False
            ),
            "meets_entry_threshold": item.pullback_pct >= entry_threshold,
            "operation_zone_checks": zone_checks,
            "matching_support": {
                "drawing_id": support.drawing_id,
                "level": support.level,
                "price": support.price,
                "lower_price": support.lower_price,
                "upper_price": support.upper_price,
            }
            if support is not None
            else None,
            "support_reference_price": support_reference_price,
            "support_distance_pct": support_distance_pct,
        }

    latest_closed_payload = None
    if confirmation is not None:
        latest_closed_payload = {
            "time": confirmation.time,
            "close_time": confirmation_close_at,
            "open": confirmation.open,
            "high": confirmation.high,
            "low": confirmation.low,
            "close": confirmation.close,
            "bullish": float(confirmation.close) > float(confirmation.open),
            "doji": float(confirmation.close) == float(confirmation.open),
            "accepted_as_bullish": is_bullish_confirmation(confirmation, accept_doji_as_bullish=accept_doji),
        }

    return {
        "symbol": symbol.upper(),
        "checked_at": checked_at,
        "closed_candle_count": len(closed),
        "detector_cycle_candle_count": len(detector_closed),
        "detector_cycle_first_time": detector_closed[0].time if detector_closed else None,
        "detector_cycle_last_time": detector_closed[-1].time if detector_closed else None,
        "executed_entry_cycle_boundaries": _executed_entry_cycle_boundaries(params),
        "last_signal_candle_time": _int_or_none(params.get("last_signal_candle_time")),
        "last_signal_pullback_low_time": _int_or_none(params.get("last_signal_pullback_low_time")),
        "entry_threshold_pct": entry_threshold,
        "entry_recovery_pct": entry_recovery_pct,
        "lookback_bars": lookback,
        "confirmation_bars": confirmation_bars,
        "accept_doji_as_bullish": accept_doji,
        "use_wicks": use_wicks,
        "use_close_confirmation": use_close_confirmation,
        "require_zone": _bool(params.get("require_zone"), True),
        "zones_enabled": _bool(params.get("enable_operation_zones"), True),
        "allow_confirmation_price_outside": _bool(params.get("operation_zone_allow_confirmation_price_outside"), False),
        "price_tolerance_pct": price_tolerance_pct,
        "time_tolerance_minutes": time_tolerance_minutes,
        "current_price": executable_price,
        "latest_closed_candle": latest_closed_payload,
        "operation_zones": [
            {
                "drawing_id": zone.drawing_id,
                "drawing_type": zone.drawing_type,
                "time1": zone.time1,
                "time2": zone.time2,
                "price_min": zone.price_min,
                "price_max": zone.price_max,
                "direction": zone.direction,
            }
            for zone in operation_zones
        ],
        "support_zones": [
            {
                "drawing_id": zone.drawing_id,
                "level": zone.level,
                "price": zone.price,
                "lower_price": zone.lower_price,
                "upper_price": zone.upper_price,
                "enabled": zone.enabled,
            }
            for zone in (support_zones or [])
        ],
        "qualifying_pullbacks": [pullback_payload(item) for item in qualifying],
        "threshold_free_pullbacks": [pullback_payload(item) for item in threshold_free],
    }


def _operation_zone_decision_metadata(
    zone: TorumV1OperationZone | None,
    *,
    confirmation: object,
    executable_price: float,
    confirmation_time_inside: bool,
    confirmation_price_inside: bool,
    allow_confirmation_price_outside: bool,
) -> dict[str, Any]:
    metadata = {
        "confirmation_time_inside_operation_zone": confirmation_time_inside,
        "confirmation_price_inside_operation_zone": confirmation_price_inside,
        "confirmation_inside_operation_zone": confirmation_time_inside and confirmation_price_inside,
        "operation_zone_allow_confirmation_price_outside": allow_confirmation_price_outside,
        "confirmation_close": float(confirmation.close),
        "executable_price": executable_price,
    }
    if zone is None:
        return metadata
    return {
        **metadata,
        "operation_zone_id": zone.drawing_id,
        "operation_zone_time1": zone.time1,
        "operation_zone_time2": zone.time2,
        "operation_zone_price_min": zone.price_min,
        "operation_zone_price_max": zone.price_max,
    }


def desired_multiplier_for_support(
    level: int | None,
    open_positions: list[object],
    *,
    params: dict[str, Any] | None = None,
) -> int:
    # This function expresses the setup's requested multiplier. Capacity and
    # risk degradation belong to plan_torum_v1_bot_exposure, where the accepted
    # multiplier is recorded explicitly. Silently reducing S3 merely because a
    # position exists made a valid triple setup appear as a simple/double one.
    del open_positions
    config = params or {}
    if level == 2:
        return max(1, min(3, _int_param(config.get("support_s2_multiplier"), 2)))
    if level == 3:
        return max(1, min(3, _int_param(config.get("support_s3_multiplier"), 3)))
    return max(1, min(3, _int_param(config.get("support_s1_multiplier"), 1)))


def _matching_support_for_entry(
    pullback: TorumV1Pullback,
    support_zones: list[TorumV1SupportZone],
    *,
    executable_price: float,
    params: dict[str, Any],
) -> tuple[TorumV1SupportZone | None, float, float | None]:
    reference_mode = str(params.get("support_reference") or "PULLBACK_LOW").upper()
    reference_price = float(executable_price) if reference_mode == "ENTRY_PRICE" else float(pullback.pullback_low)
    max_distance_pct = _nonnegative_float_param(params.get("support_max_distance_pct"), 0.0)

    matches: list[tuple[TorumV1SupportZone, float]] = []
    for support in support_zones:
        if not support.enabled:
            continue
        if support.lower_price <= reference_price <= support.upper_price:
            distance_pct = 0.0
        else:
            nearest_boundary = support.lower_price if reference_price < support.lower_price else support.upper_price
            distance_pct = abs(reference_price - nearest_boundary) / abs(reference_price) * 100.0 if reference_price else float("inf")
            if max_distance_pct <= 0 or distance_pct > max_distance_pct:
                continue
        matches.append((support, distance_pct))

    if not matches:
        return None, reference_price, None
    support, distance_pct = sorted(
        matches,
        key=lambda item: (-item[0].level, item[1], abs(float(item[0].price) - reference_price)),
    )[0]
    return support, reference_price, distance_pct


def _matching_support_for_pullback(pullback: TorumV1Pullback, support_zones: list[TorumV1SupportZone]) -> TorumV1SupportZone | None:
    # Backward-compatible helper used by external tests/imports.
    support, _price, _distance = _matching_support_for_entry(
        pullback,
        support_zones,
        executable_price=float(pullback.pullback_low),
        params={"support_reference": "PULLBACK_LOW", "support_max_distance_pct": 0.0},
    )
    return support


def pullback_debug_payload(
    candles_m5: list[object],
    params: dict[str, Any],
    *,
    live_price: float | None = None,
    live_time: datetime | None = None,
    live_cache_key: str | None = None,
) -> list[dict[str, Any]]:
    if not _bool(params.get("pullback_enabled"), True):
        return []

    threshold = _pullback_threshold(params)
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    recovery_pct = _nonnegative_float_param(params.get("pullback_recovery_pct"), 0.10)
    confirmation_bars = _int_param(params.get("pullback_end_confirmation_bars"), 1)
    max_count = _int_param(params.get("pullback_max_count"), 10)
    min_bars_between = _nonnegative_int_param(params.get("pullback_min_bars_between"), 0)
    swing_confirm_bars = _nonnegative_int_param(params.get("pullback_swing_confirm_bars"), 1)
    allow_peak_extension = _bool(params.get("pullback_allow_peak_extension"), True)
    require_bearish_leg = _bool(params.get("pullback_require_bearish_leg"), True)
    min_bearish_candles = _nonnegative_int_param(params.get("pullback_min_bearish_candles"), 1)
    min_lower_close_candles = _nonnegative_int_param(params.get("pullback_min_lower_close_candles"), 1)
    disallow_same_candle_peak_low = _bool(params.get("pullback_disallow_same_candle_peak_low"), True)
    impulse_green_filter_enabled = _bool(params.get("pullback_impulse_green_filter_enabled"), True)
    show_only_live = _bool(params.get("pullback_show_only_live"), False)
    show_labels = _bool(params.get("pullback_show_labels"), True)
    label_decimals = max(0, min(6, _nonnegative_int_param(params.get("pullback_label_decimals"), 2)))
    line_width = max(1, min(6, _nonnegative_int_param(params.get("pullback_line_width"), 2)))
    opacity = max(0.1, min(1.0, _nonnegative_float_param(params.get("pullback_opacity"), 0.95)))

    candles = _sorted_candles(candles_m5)
    segments = _pullback_cycle_segments(candles, params)
    pullbacks: list[TorumV1Pullback] = []
    for segment_index, segment in enumerate(segments):
        is_current_segment = segment_index == len(segments) - 1
        pullbacks.extend(
            detect_pullbacks(
                segment,
                threshold=threshold,
                lookback=lookback,
                recovery_pct=recovery_pct,
                end_confirmation_bars=confirmation_bars,
                max_count=None,
                min_bars_between=min_bars_between,
                use_wicks=_bool(params.get("pullback_use_wicks"), True),
                use_close_confirmation=_bool(params.get("pullback_use_close_confirmation"), True),
                accept_doji_as_recovery=_bool(params.get("confirmation_ignore_doji"), True),
                live_update_enabled=(
                    is_current_segment and _bool(params.get("pullback_live_update_enabled"), True)
                ),
                live_price=live_price if is_current_segment else None,
                live_time=live_time if is_current_segment else None,
                live_anchor_to_low=_bool(params.get("pullback_live_anchor_to_low"), True),
                live_cache_key=live_cache_key if is_current_segment else None,
                swing_confirm_bars=swing_confirm_bars,
                allow_peak_extension=allow_peak_extension,
                require_bearish_leg=require_bearish_leg,
                min_bearish_candles=min_bearish_candles,
                min_lower_close_candles=min_lower_close_candles,
                disallow_same_candle_peak_low=disallow_same_candle_peak_low,
                impulse_green_filter_enabled=impulse_green_filter_enabled,
            )
        )
    pullbacks = _latest_pullbacks(pullbacks, max_count=max_count)
    if show_only_live:
        pullbacks = [pullback for pullback in pullbacks if pullback.is_live]

    result: list[dict[str, Any]] = []

    for pullback in pullbacks:
        result.append(
            {
                "swing_high_time": int(pullback.swing_high_time.timestamp()),
                "swing_high": pullback.swing_high,
                "pullback_low_time": int(pullback.pullback_low_time.timestamp()),
                "pullback_low": pullback.pullback_low,
                "pullback_pct": pullback.pullback_pct,
                "threshold_pct": threshold,
                "threshold_touched": threshold > 0 and pullback.pullback_pct >= threshold,
                "is_live": pullback.is_live,
                "label": f"PB {pullback.pullback_pct:.{label_decimals}f}%" if show_labels else "",
                "line_width": line_width,
                "opacity": opacity,
            }
        )

    return result


class TorumV1StatusService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def status_for_user(self, user_id: int | None, at_time: datetime | None = None) -> TorumV1Status:
        checked_at = _as_utc(at_time or datetime.now(UTC))
        strategy_settings = get_global_strategy_settings(self.db)
        configs = self._configs_by_symbol(user_id)
        assets: dict[str, TorumV1AssetStatus] = {}

        for symbol in SUPPORTED_SYMBOLS:
            assets[symbol] = self.asset_status(symbol, configs.get(symbol), strategy_settings.strategies_enabled, checked_at)

        return TorumV1Status(
            strategy_key=TORUM_V1_KEY,
            enabled=bool(strategy_settings.strategies_enabled and any(asset.enabled for asset in assets.values())),
            use_news=any(_use_news(config) for config in configs.values()),
            server_time=checked_at,
            madrid_time=checked_at.astimezone(MADRID_TZ),
            assets=assets,
        )

    def asset_status(
        self,
        symbol: str,
        config: StrategyConfig | None,
        strategies_enabled: bool,
        at_time: datetime | None = None,
    ) -> TorumV1AssetStatus:
        checked_at = _as_utc(at_time or datetime.now(UTC))
        madrid_now = checked_at.astimezone(MADRID_TZ)
        bot_params = _symbol_params(symbol, config)
        bot_enabled = bool(strategies_enabled and config is not None and config.enabled and _bool(bot_params.get("enabled"), True))
        params = bot_params if bot_enabled else _default_status_params(symbol)
        preferred_timeframe = _timeframe(params.get("timeframe"))
        unlock_mode = _unlock_timeframe_mode(params.get("unlock_timeframe_mode"))
        timeframe = "H2/H3" if unlock_mode == "BOTH" else unlock_mode
        session_start = _hhmm(params.get("session_start"), _default_session_start(symbol))
        session_end = _hhmm(params.get("session_end"), _default_session_end(symbol))
        base = {
            "symbol": symbol,
            "enabled": bot_enabled,
            "timeframe": timeframe,
            "session_start": session_start,
            "session_end": session_end,
            "active_config_id": config.id if config is not None else None,
        }

        session_days = params.get("session_days")
        allowed_days = {str(item).upper() for item in session_days} if isinstance(session_days, list) else {"MO", "TU", "WE", "TH", "FR"}
        weekday_key = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[madrid_now.weekday()]
        if weekday_key not in allowed_days:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="outside_session_day", unlocked_at=None, blocked_by_news=False)

        if self._is_news_blocked(symbol, config if bot_enabled else None, checked_at):
            return TorumV1AssetStatus(**base, status="LOCKED", reason="news_zone", unlocked_at=None, blocked_by_news=True)

        session_start_dt = _local_dt(madrid_now.date(), session_start)
        session_end_dt = _local_dt(madrid_now.date(), session_end)
        if madrid_now < session_start_dt or madrid_now >= session_end_dt:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="outside_session", unlocked_at=None, blocked_by_news=False)

        unlocked_at, reason = self._unlocked_at(symbol, madrid_now, session_start, session_end, params)
        if unlocked_at is None:
            return TorumV1AssetStatus(**base, status="LOCKED", reason=reason, unlocked_at=None, blocked_by_news=False)

        return TorumV1AssetStatus(**base, status="UNLOCKED", reason=reason, unlocked_at=unlocked_at, blocked_by_news=False)

    def unlock_diagnostic_snapshot(
        self,
        symbol: str,
        config: StrategyConfig | None,
        strategies_enabled: bool,
        at_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Return the candle/session evidence used by the unlock decision.

        This is intentionally side-effect free and is used by the automatic
        strategy runner only when writing diagnostics. It makes it possible to
        explain an apparent LOCKED/UNLOCKED mismatch without guessing from the
        chart or from the UI icon.
        """

        normalized_symbol = symbol.upper()
        checked_at = _as_utc(at_time or datetime.now(UTC))
        madrid_now = checked_at.astimezone(MADRID_TZ)
        bot_params = _symbol_params(normalized_symbol, config)
        bot_enabled = bool(
            strategies_enabled
            and config is not None
            and config.enabled
            and _bool(bot_params.get("enabled"), True)
        )
        params = bot_params if bot_enabled else _default_status_params(normalized_symbol)
        preferred_timeframe = _timeframe(params.get("timeframe"))
        unlock_mode = _unlock_timeframe_mode(params.get("unlock_timeframe_mode"))
        session_start = _hhmm(params.get("session_start"), _default_session_start(normalized_symbol))
        session_end = _hhmm(params.get("session_end"), _default_session_end(normalized_symbol))
        status = self.asset_status(normalized_symbol, config, strategies_enabled, checked_at)
        windows_payload: list[dict[str, Any]] = []
        for timeframe, start_local, end_local in _evaluation_windows(
            normalized_symbol,
            madrid_now.date(),
            session_start,
            session_end,
            preferred_timeframe=preferred_timeframe,
            unlock_mode=unlock_mode,
        ):
            duration = end_local - start_local
            current = self._aggregate_window(
                normalized_symbol,
                start_local,
                end_local,
                preferred_timeframe=timeframe,
            )
            previous = self._aggregate_window(
                normalized_symbol,
                start_local - duration,
                start_local,
                preferred_timeframe=timeframe,
            )
            windows_payload.append(
                {
                    "timeframe": timeframe,
                    "start_local": start_local,
                    "end_local": end_local,
                    "window_closed": madrid_now >= end_local,
                    "current": _aggregated_candle_diagnostic_payload(current),
                    "previous": _aggregated_candle_diagnostic_payload(previous),
                }
            )
        return {
            "checked_at_utc": checked_at,
            "madrid_time": madrid_now,
            "symbol": normalized_symbol,
            "config_id": config.id if config is not None else None,
            "config_enabled": config.enabled if config is not None else None,
            "strategies_enabled": strategies_enabled,
            "bot_enabled": bot_enabled,
            "status": status.status,
            "reason": status.reason,
            "blocked_by_news": status.blocked_by_news,
            "unlocked_at": status.unlocked_at,
            "session_start": session_start,
            "session_end": session_end,
            "session_days": params.get("session_days"),
            "preferred_timeframe": preferred_timeframe,
            "unlock_mode": unlock_mode,
            "unlock_bullish_close_enabled": _bool(params.get("unlock_bullish_close_enabled"), True),
            "unlock_two_bearish_hold_low_enabled": _bool(
                params.get("unlock_two_bearish_hold_low_enabled"),
                True,
            ),
            "unlock_min_body_pct": _nonnegative_float_param(params.get("unlock_min_body_pct"), 0.0),
            "evaluation_windows": windows_payload,
        }

    def bot_block_reasons(self, symbol: str, user_id: int | None, at_time: datetime | None = None) -> list[str]:
        checked_at = _as_utc(at_time or datetime.now(UTC))
        strategy_settings = get_global_strategy_settings(self.db)
        config = self._configs_by_symbol(user_id).get(symbol.upper())
        if config is None or not config.enabled:
            if self._is_news_blocked(symbol.upper(), config, checked_at):
                return [f"BOT bloqueado por noticia activa en {symbol.upper()}"]
            return []

        status = self.asset_status(symbol.upper(), config, strategy_settings.strategies_enabled, checked_at)
        if status.status == "UNLOCKED":
            return []
        if status.blocked_by_news:
            return [f"BOT bloqueado por noticia activa en {symbol.upper()}"]
        return [f"BOT bloqueado por Torum V1 en {symbol.upper()}: {status.reason}"]

    def _configs_by_symbol(self, user_id: int | None) -> dict[str, StrategyConfig]:
        rows = list(
            self.db.scalars(
                select(StrategyConfig)
                .where(StrategyConfig.strategy_key == TORUM_V1_KEY, StrategyConfig.user_id == user_id)
                .order_by(StrategyConfig.enabled.desc(), StrategyConfig.id)
            )
        )
        configs: dict[str, StrategyConfig] = {}
        for config in rows:
            symbol = config.internal_symbol.upper()
            if symbol in SUPPORTED_SYMBOLS and symbol not in configs:
                configs[symbol] = config
        return configs

    def _unlocked_at(
        self,
        symbol: str,
        madrid_now: datetime,
        session_start: str,
        session_end: str,
        params: dict[str, object],
    ) -> tuple[datetime | None, str]:
        preferred_timeframe = _timeframe(params.get("timeframe"))
        unlock_mode = _unlock_timeframe_mode(params.get("unlock_timeframe_mode"))
        windows = _evaluation_windows(
            symbol,
            madrid_now.date(),
            session_start,
            session_end,
            preferred_timeframe=preferred_timeframe,
            unlock_mode=unlock_mode,
        )
        last_reason = "waiting_closed_candle"

        for timeframe, start_local, end_local in windows:
            if madrid_now < end_local:
                return None, "waiting_closed_candle"

            duration = end_local - start_local
            current = self._aggregate_window(symbol, start_local, end_local, preferred_timeframe=timeframe)
            previous = self._aggregate_window(symbol, start_local - duration, start_local, preferred_timeframe=timeframe)
            if current is None:
                last_reason = "missing_current_candle"
                continue

            min_body_pct = _nonnegative_float_param(params.get("unlock_min_body_pct"), 0.0)
            body_pct = abs(current.close - current.open) / current.open * 100.0 if current.open else 0.0
            if _bool(params.get("unlock_bullish_close_enabled"), True) and current.close > current.open and body_pct >= min_body_pct:
                return end_local.astimezone(UTC), "bullish_closed_candle"
            if previous is None:
                last_reason = "missing_previous_candle"
                continue
            current_bearish = current.close < current.open
            previous_bearish = previous.close < previous.open
            if (
                _bool(params.get("unlock_two_bearish_hold_low_enabled"), True)
                and current_bearish
                and previous_bearish
                and current.low >= previous.low
            ):
                return end_local.astimezone(UTC), "held_previous_low"
            if not current_bearish:
                last_reason = "current_candle_not_bearish"
            elif not previous_bearish:
                last_reason = "previous_candle_not_bearish"
            else:
                last_reason = "broke_previous_low"

        return None, last_reason

    def _aggregate_window(
        self,
        symbol: str,
        start_local: datetime,
        end_local: datetime,
        preferred_timeframe: str | None = None,
    ) -> AggregatedCandle | None:
        start_utc = _madrid_local_to_broker_chart_utc(start_local)
        end_utc = _madrid_local_to_broker_chart_utc(end_local)
        timeframe_order = _aggregate_timeframe_order(preferred_timeframe)
        for timeframe in timeframe_order:
            rows = list(
                self.db.scalars(
                    select(Candle)
                    .where(
                        Candle.internal_symbol == symbol,
                        Candle.timeframe == timeframe,
                        Candle.time >= start_utc,
                        Candle.time < end_utc,
                    )
                    .order_by(Candle.time)
                )
            )
            if not rows:
                continue
            return AggregatedCandle(
                start_time=start_utc,
                end_time=end_utc,
                open=rows[0].open,
                high=max(row.high for row in rows),
                low=min(row.low for row in rows),
                close=rows[-1].close,
            )
        return None

    def _is_news_blocked(self, symbol: str, config: StrategyConfig | None, at_time: datetime) -> bool:
        if config is not None and not _use_news(config):
            return False
        # Per-impact news rules are materialized as no-trade zones.  The legacy
        # block_trading_during_news flag is intentionally not used as a second
        # gate here, otherwise a BLOCK_BOT rule configured in the new editor can
        # be silently disabled by an older global boolean.
        get_global_news_settings(self.db)  # ensure global settings are seeded
        zones = NoTradeZoneService(self.db).get_active_zones(symbol, at_time)
        return any(zone.blocks_trading for zone in zones)


def _symbol_params(symbol: str, config: StrategyConfig | None) -> dict[str, object]:
    params = dict(config.params_json or {}) if config is not None else {}
    assets = params.get("assets")
    if isinstance(assets, dict):
        symbol_params = assets.get(symbol)
        if isinstance(symbol_params, dict):
            params.update(symbol_params)
    return params


def _default_status_params(symbol: str) -> dict[str, object]:
    return {
        "use_news": True,
        "timeframe": "H2",
        "session_start": _default_session_start(symbol),
        "session_end": _default_session_end(symbol),
    }


def _use_news(config: StrategyConfig | None) -> bool:
    if config is None:
        return True
    return _bool((config.params_json or {}).get("use_news"), True)


def _bool(value: object, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _float_param(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _nonnegative_float_param(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _int_param(value: object, fallback: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else fallback


def _nonnegative_int_param(value: object, fallback: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed >= 0 else fallback


def _pullback_threshold(params: dict[str, Any]) -> float:
    if "pullback_min_pct" in params:
        return _nonnegative_float_param(params.get("pullback_min_pct"), 0.0)
    return _nonnegative_float_param(params.get("pullback_threshold_pct"), 0.0)


def _pullback_entry_threshold(params: dict[str, Any]) -> float:
    if "pullback_entry_min_pct" in params:
        return _nonnegative_float_param(params.get("pullback_entry_min_pct"), 0.20)
    return _nonnegative_float_param(params.get("pullback_threshold_pct"), 0.20)


def _int_or_none(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _sorted_candles(candles: list[object]) -> list[object]:
    return sorted(
        [
            candle
            for candle in candles
            if hasattr(candle, "time")
            and hasattr(candle, "open")
            and hasattr(candle, "high")
            and hasattr(candle, "low")
            and hasattr(candle, "close")
        ],
        key=lambda candle: _as_utc(candle.time),
    )


def _closed_entry_candles(candles: list[object], now: datetime, timeframe_seconds: int = 300) -> list[object]:
    checked_at = _as_utc(now)
    return [
        candle
        for candle in _sorted_candles(candles)
        if _as_utc(candle.time) + timedelta(seconds=timeframe_seconds) <= checked_at
    ]


def _operation_zone_from_payload(
    drawing_id: str,
    drawing_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> TorumV1OperationZone | None:
    time1 = _int_or_none(payload.get("time1"))
    raw_time2 = payload.get("time2")
    time2 = None if raw_time2 is None else _int_or_none(raw_time2)

    if drawing_type == "rectangle":
        price_a = _float_or_none(payload.get("price1"))
        price_b = _float_or_none(payload.get("price2"))
    else:
        price_a = _float_or_none(payload.get("price_min"))
        price_b = _float_or_none(payload.get("price_max"))

    if time1 is None or price_a is None or price_b is None:
        return None

    direction = str(metadata.get("direction") or payload.get("direction") or "BUY").upper()
    if direction != "BUY":
        return None

    return TorumV1OperationZone(
        drawing_id=drawing_id,
        drawing_type=drawing_type,
        time1=time1,
        time2=time2,
        price_min=min(price_a, price_b),
        price_max=max(price_a, price_b),
        direction="BUY",
    )


def _aggregated_candle_diagnostic_payload(candle: AggregatedCandle | None) -> dict[str, Any] | None:
    if candle is None:
        return None
    body_pct = abs(candle.close - candle.open) / candle.open * 100.0 if candle.open else 0.0
    return {
        "time": candle.time,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "bullish": candle.close > candle.open,
        "bearish": candle.close < candle.open,
        "doji": candle.close == candle.open,
        "body_pct": body_pct,
    }


def _float_or_none(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _support_level(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed in {1, 2, 3} else None


def _timeframe(value: object) -> str:
    candidate = str(value or "H2").upper()
    return candidate if candidate in SUPPORTED_EVALUATION_TIMEFRAMES else "H2"


def _unlock_timeframe_mode(value: object) -> str:
    candidate = str(value or "BOTH").upper()
    return candidate if candidate in {"BOTH", "H2", "H3"} else "BOTH"


def _aggregate_timeframe_order(preferred_timeframe: str | None) -> tuple[str, ...]:
    if preferred_timeframe == "H2":
        return ("H2", "H1", "M5", "M1")
    if preferred_timeframe == "H3":
        return ("H3", "H1", "M5", "M1")
    return ("H1", "M5", "M1", "H2", "H3")


def _hhmm(value: object, fallback: str) -> str:
    candidate = str(value or fallback)
    try:
        time.fromisoformat(candidate)
    except ValueError:
        return fallback
    return candidate[:5]


def _default_session_start(symbol: str) -> str:
    return "09:00" if symbol == "XAUEUR" else "15:30"


def _default_session_end(symbol: str) -> str:
    return "15:00" if symbol == "XAUEUR" else "21:00"


def _evaluation_start(symbol: str, session_start: str) -> str:
    if symbol == "XAUUSD":
        return "15:00"
    return session_start


def _evaluation_windows(
    symbol: str,
    day: object,
    session_start: str,
    session_end: str,
    preferred_timeframe: str | None = None,
    unlock_mode: str = "BOTH",
) -> list[tuple[str, datetime, datetime]]:
    start_local = _local_dt(day, _evaluation_start(symbol, session_start))
    end_limit = _local_dt(day, session_end)
    windows: list[tuple[str, datetime, datetime]] = []

    candidates = (("H2", 2), ("H3", 3))
    if unlock_mode in {"H2", "H3"}:
        candidates = tuple(item for item in candidates if item[0] == unlock_mode)
    for timeframe, hours in candidates:
        duration = timedelta(hours=hours)
        current_start = start_local
        while current_start + duration <= end_limit:
            windows.append((timeframe, current_start, current_start + duration))
            current_start += duration

    return sorted(
        windows,
        key=lambda item: (
            item[2],
            0 if item[0] == preferred_timeframe else 1,
            2 if item[0] == "H2" else 3,
            item[1],
        ),
    )


def _local_dt(day: object, hhmm: str) -> datetime:
    parsed = time.fromisoformat(hhmm)
    return datetime.combine(day, parsed, tzinfo=MADRID_TZ)


def _madrid_local_to_broker_chart_utc(value: datetime) -> datetime:
    broker_wall_time = value.astimezone(_broker_time_zone())
    return broker_wall_time.replace(tzinfo=UTC)


def _broker_time_zone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().chart_broker_time_zone)
    except Exception:
        return DEFAULT_BROKER_TZ


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

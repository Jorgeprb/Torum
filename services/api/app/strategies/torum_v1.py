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
    "pullback_recovery_pct": 0.10,
    "pullback_end_confirmation_bars": 1,
    "pullback_min_bars_between": 0,
    "pullback_use_wicks": True,
    "pullback_use_close_confirmation": True,
    "pullback_live_update_enabled": True,
    "pullback_show_labels": True,
    "pullback_show_only_live": False,
    "pullback_label_decimals": 2,
    "pullback_line_width": 2,
    "pullback_opacity": 0.95,
    "show_pullback_debug": False,
    "require_zone": True,
    "one_position_per_symbol": False,
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
    live_update_enabled: bool = True,
    live_price: float | None = None,
    live_time: datetime | None = None,
    swing_confirm_bars: int = 1,
    allow_peak_extension: bool = True,
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
            )
            if active is not None:
                confirmed_recovery_bars = 0
            continue

        if allow_peak_extension:
            active_peak_index = _index_for_time(candles, active.swing_high_time, fallback=index)
            candidate_peak_index = _highest_high_index(
                candles,
                max(segment_start_index, active_peak_index, index - safe_lookback + 1),
                index,
            )
            candidate_peak = candles[candidate_peak_index]
            candidate_peak_time = _as_utc(candidate_peak.time)
            if candidate_peak_time > active.swing_high_time and float(candidate_peak.high) > active.swing_high:
                updated = _pullback_from_peak_window(
                    candles,
                    candidate_peak_index,
                    index,
                    threshold=safe_threshold,
                    use_wicks=use_wicks,
                )
                if updated is None:
                    peak = candidate_peak
                    active = None
                    segment_start_index = candidate_peak_index
                else:
                    active = updated
                confirmed_recovery_bars = 0
                continue

        if _as_utc(candle.time) < active.swing_high_time:
            continue

        if low < active.pullback_low:
            active = _updated_pullback_low(active, candle.time, low)
            confirmed_recovery_bars = 0
            continue

        recovered = float(candle.close) >= active.pullback_low * (1 + safe_recovery_pct / 100)
        if use_close_confirmation:
            recovered = recovered and float(candle.close) > float(candle.open)
        confirmed_recovery_bars = confirmed_recovery_bars + 1 if recovered else 0
        if confirmed_recovery_bars >= required_recovery_bars:
            pullbacks.append(active)
            peak = candle
            active = None
            confirmed_recovery_bars = 0
            bars_until_next_pullback = safe_min_bars_between
            segment_start_index = index

    active = (
        _apply_live_pullback_update(
            active=active,
            peak=peak,
            last_candle=candles[-1],
            live_price=live_price,
            live_time=live_time,
            threshold=safe_threshold,
            use_wicks=use_wicks,
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
) -> TorumV1Pullback | None:
    if peak_index > end_index:
        return None
    peak = candles[peak_index]
    swing_high = float(peak.high)
    if swing_high <= 0:
        return None
    low_start_index = peak_index + 1 if peak_index < end_index else peak_index
    low_index = _lowest_pullback_index(candles, low_start_index, end_index, use_wicks)
    low_candle = candles[low_index]
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
    )


def _apply_live_pullback_update(
    *,
    active: TorumV1Pullback | None,
    peak: object,
    last_candle: object,
    live_price: float | None,
    live_time: datetime | None,
    threshold: float,
    use_wicks: bool,
) -> TorumV1Pullback | None:
    if live_price is None:
        return active

    del last_candle, use_wicks
    live_low = float(live_price)
    low_time = _as_utc(live_time or datetime.now(UTC))

    if active is not None:
        return _updated_pullback_low(active, low_time, live_low) if live_low < active.pullback_low else active

    swing_high = float(peak.high)
    if swing_high <= 0 or live_low >= swing_high:
        return None

    pullback_pct = _pullback_pct(swing_high, live_low)
    if pullback_pct < threshold:
        return None

    return TorumV1Pullback(
        swing_high_time=_as_utc(peak.time),
        swing_high=swing_high,
        pullback_low_time=low_time,
        pullback_low=live_low,
        pullback_pct=pullback_pct,
    )


def is_bullish_confirmation(candle: object) -> bool:
    return float(candle.close) > float(candle.open)


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


def is_candle_inside_operation_zone(candle: object, zone: TorumV1OperationZone, timeframe_seconds: int = 300) -> bool:
    candle_time = int(_as_utc(candle.time).timestamp())
    candle_close_time = candle_time + timeframe_seconds
    close_price = float(candle.close)

    if candle_close_time < zone.time1:
        return False
    if zone.time2 is not None and candle_close_time > zone.time2:
        return False
    return zone.price_min <= close_price <= zone.price_max


def is_pullback_low_inside_operation_zone(pullback: TorumV1Pullback, zone: TorumV1OperationZone, timeframe_seconds: int = 300) -> bool:
    del timeframe_seconds
    low_time = int(_as_utc(pullback.pullback_low_time).timestamp())
    low_price = float(pullback.pullback_low)

    if low_time < zone.time1:
        return False
    if zone.time2 is not None and low_time > zone.time2:
        return False
    return zone.price_min <= low_price <= zone.price_max


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

    if not is_bullish_confirmation(confirmation):
        return TorumV1BuyDecision(False, "waiting_bullish_confirmation")

    if not _bool(params.get("pullback_enabled"), True):
        return TorumV1BuyDecision(False, "pullback_disabled")

    entry_threshold = _pullback_entry_threshold(params)
    if entry_threshold <= 0:
        return TorumV1BuyDecision(False, "missing_pullback_entry_min_pct")
    threshold = entry_threshold
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    recovery_pct = _nonnegative_float_param(params.get("pullback_recovery_pct"), 0.10)
    confirmation_bars = _int_param(params.get("pullback_end_confirmation_bars"), 1)
    min_bars_between = _nonnegative_int_param(params.get("pullback_min_bars_between"), 0)
    swing_confirm_bars = _nonnegative_int_param(params.get("pullback_swing_confirm_bars"), 1)
    allow_peak_extension = _bool(params.get("pullback_allow_peak_extension"), True)
    pullbacks = [
        pullback
        for pullback in detect_pullbacks(
            closed,
            threshold,
            lookback,
            recovery_pct,
            confirmation_bars,
            max_count=_int_param(params.get("pullback_max_count"), 10),
            min_bars_between=min_bars_between,
            use_wicks=_bool(params.get("pullback_use_wicks"), True),
            use_close_confirmation=_bool(params.get("pullback_use_close_confirmation"), True),
            live_update_enabled=False,
            swing_confirm_bars=swing_confirm_bars,
            allow_peak_extension=allow_peak_extension,
        )
        if not pullback.is_live and pullback.pullback_low_time < confirmation_time
        and pullback.pullback_pct >= entry_threshold
    ]
    if not pullbacks:
        return TorumV1BuyDecision(False, "missing_pullback")

    pullback = pullbacks[-1]
    require_zone = _bool(params.get("require_zone"), True)
    zones_enabled = _bool(params.get("enable_operation_zones"), True)
    matching_zone = None
    if zones_enabled:
        matching_zone = next(
            (
                zone
                for zone in operation_zones
                if zone.direction == "BUY" and is_pullback_low_inside_operation_zone(pullback, zone)
            ),
            None,
        )

    if require_zone and matching_zone is None:
        return TorumV1BuyDecision(False, "pullback_low_outside_operation_zone", confirmation_time, pullback)

    last_pullback_time = _int_or_none(params.get("last_signal_pullback_low_time"))
    pullback_low_time_int = int(pullback.pullback_low_time.timestamp())
    if last_pullback_time == pullback_low_time_int:
        return TorumV1BuyDecision(False, "duplicate_signal_pullback", confirmation_time, pullback, matching_zone)

    matching_support = _matching_support_for_pullback(pullback, support_zones or [])
    desired_multiplier = desired_multiplier_for_support(
        matching_support.level if matching_support is not None else None,
        open_positions or [],
    )

    metadata = {
        "symbol": symbol.upper(),
        "entry_timeframe": "M5",
        "entry_setup": "pullback_low_inside_zone_bullish_confirmation",
        "confirmation_candle_time": confirmation_time_int,
        "pullback_pct": pullback.pullback_pct,
        "swing_high": pullback.swing_high,
        "swing_high_time": int(pullback.swing_high_time.timestamp()),
        "pullback_low": pullback.pullback_low,
        "pullback_low_time": pullback_low_time_int,
        "pullback_entry_min_pct": entry_threshold,
        "operation_zone_id": matching_zone.drawing_id if matching_zone else None,
        "support_zone_id": matching_support.drawing_id if matching_support else None,
        "support_level": matching_support.level if matching_support else None,
        "desired_multiplier": desired_multiplier,
    }
    return TorumV1BuyDecision(True, "buy_pullback_confirmed_inside_zone", confirmation_time, pullback, matching_zone, matching_support, metadata)


def desired_multiplier_for_support(level: int | None, open_positions: list[object]) -> int:
    if level == 2:
        return 2
    if level == 3:
        return 3 if len(open_positions) == 0 else 2
    return 1


def _matching_support_for_pullback(pullback: TorumV1Pullback, support_zones: list[TorumV1SupportZone]) -> TorumV1SupportZone | None:
    low = float(pullback.pullback_low)
    matches = [
        support
        for support in support_zones
        if support.enabled and support.lower_price <= low <= support.upper_price
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda support: (-support.level, abs(float(support.price) - low)))[0]


def pullback_debug_payload(
    candles_m5: list[object],
    params: dict[str, Any],
    *,
    live_price: float | None = None,
    live_time: datetime | None = None,
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
    show_only_live = _bool(params.get("pullback_show_only_live"), False)
    show_labels = _bool(params.get("pullback_show_labels"), True)
    label_decimals = max(0, min(6, _nonnegative_int_param(params.get("pullback_label_decimals"), 2)))
    line_width = max(1, min(6, _nonnegative_int_param(params.get("pullback_line_width"), 2)))
    opacity = max(0.1, min(1.0, _nonnegative_float_param(params.get("pullback_opacity"), 0.95)))

    candles = _sorted_candles(candles_m5)
    pullbacks = detect_pullbacks(
        candles,
        threshold=threshold,
        lookback=lookback,
        recovery_pct=recovery_pct,
        end_confirmation_bars=confirmation_bars,
        max_count=max_count,
        min_bars_between=min_bars_between,
        use_wicks=_bool(params.get("pullback_use_wicks"), True),
        use_close_confirmation=_bool(params.get("pullback_use_close_confirmation"), True),
        live_update_enabled=_bool(params.get("pullback_live_update_enabled"), True),
        live_price=live_price,
        live_time=live_time,
        swing_confirm_bars=swing_confirm_bars,
        allow_peak_extension=allow_peak_extension,
    )
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
        timeframe = "H2/H3"
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

        if self._is_news_blocked(symbol, config if bot_enabled else None, checked_at):
            return TorumV1AssetStatus(**base, status="LOCKED", reason="news_zone", unlocked_at=None, blocked_by_news=True)

        session_start_dt = _local_dt(madrid_now.date(), session_start)
        session_end_dt = _local_dt(madrid_now.date(), session_end)
        if madrid_now < session_start_dt or madrid_now >= session_end_dt:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="outside_session", unlocked_at=None, blocked_by_news=False)

        unlocked_at, reason = self._unlocked_at(symbol, madrid_now, session_start, session_end)
        if unlocked_at is None:
            return TorumV1AssetStatus(**base, status="LOCKED", reason=reason, unlocked_at=None, blocked_by_news=False)

        return TorumV1AssetStatus(**base, status="UNLOCKED", reason=reason, unlocked_at=unlocked_at, blocked_by_news=False)

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
    ) -> tuple[datetime | None, str]:
        windows = _evaluation_windows(symbol, madrid_now.date(), session_start, session_end)
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

            if current.close > current.open:
                return end_local.astimezone(UTC), "bullish_closed_candle"
            if previous is None:
                last_reason = "missing_previous_candle"
                continue
            current_bearish = current.close < current.open
            previous_bearish = previous.close < previous.open
            if current_bearish and previous_bearish and current.low >= previous.low:
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
        news_settings = get_global_news_settings(self.db)
        if not news_settings.block_trading_during_news:
            return False
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
) -> list[tuple[str, datetime, datetime]]:
    start_local = _local_dt(day, _evaluation_start(symbol, session_start))
    end_limit = _local_dt(day, session_end)
    windows: list[tuple[str, datetime, datetime]] = []

    for timeframe, hours in (("H2", 2), ("H3", 3)):
        duration = timedelta(hours=hours)
        current_start = start_local
        while current_start + duration <= end_limit:
            windows.append((timeframe, current_start, current_start + duration))
            current_start += duration

    return sorted(
        windows,
        key=lambda item: (
            item[2],
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

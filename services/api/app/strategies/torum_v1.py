from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.news.service import get_global_news_settings
from app.no_trade_zones.service import NoTradeZoneService
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings

TORUM_V1_KEY = "torum_v1"
MADRID_TZ = ZoneInfo("Europe/Madrid")
SUPPORTED_SYMBOLS = ("XAUEUR", "XAUUSD")
SUPPORTED_EVALUATION_TIMEFRAMES = ("H2", "H3")


DEFAULT_TORUM_V1_PARAMS: dict[str, object] = {
    "use_news": True,
    "enable_operation_zones": True,
    "entry_timeframe": "M5",
    "pullback_threshold_pct": 0.20,
    "pullback_lookback_bars": 12,
    "show_pullback_debug": False,
    "require_zone": True,
    "one_position_per_symbol": True,
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
class TorumV1BuyDecision:
    should_buy: bool
    reason: str
    confirmation_candle_time: datetime | None = None
    pullback: TorumV1Pullback | None = None
    zone: TorumV1OperationZone | None = None
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


def detect_pullbacks(candles_m5: list[object], threshold: float = 0.20, lookback: int = 12) -> list[TorumV1Pullback]:
    candles = _sorted_candles(candles_m5)
    safe_lookback = max(1, int(lookback))
    pullbacks: list[TorumV1Pullback] = []

    for low_index in range(1, len(candles)):
        current = candles[low_index]
        previous_window = candles[max(0, low_index - safe_lookback):low_index]
        if not previous_window:
            continue

        swing = max(previous_window, key=lambda candle: float(candle.high))
        swing_high = float(swing.high)
        current_low = float(current.low)
        if swing_high <= 0 or current_low >= swing_high:
            continue

        pullback_pct = (swing_high - current_low) / swing_high * 100
        if pullback_pct >= threshold:
            pullbacks.append(
                TorumV1Pullback(
                    swing_high_time=_as_utc(swing.time),
                    swing_high=swing_high,
                    pullback_low_time=_as_utc(current.time),
                    pullback_low=current_low,
                    pullback_pct=pullback_pct,
                )
            )

    return pullbacks


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


def is_candle_inside_operation_zone(candle: object, zone: TorumV1OperationZone, timeframe_seconds: int = 300) -> bool:
    candle_time = int(_as_utc(candle.time).timestamp())
    candle_close_time = candle_time + timeframe_seconds
    close_price = float(candle.close)

    if candle_close_time < zone.time1:
        return False
    if zone.time2 is not None and candle_close_time > zone.time2:
        return False
    return zone.price_min <= close_price <= zone.price_max


def should_buy_torum_v1(
    *,
    symbol: str,
    candles_m5: list[object],
    operation_zones: list[TorumV1OperationZone],
    params: dict[str, Any],
    now: datetime | None = None,
    open_positions: list[object] | None = None,
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

    threshold = _float_param(params.get("pullback_threshold_pct"), 0.20)
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    pullbacks = [pullback for pullback in detect_pullbacks(closed[:-1], threshold, lookback) if pullback.pullback_low_time < confirmation_time]
    if not pullbacks:
        return TorumV1BuyDecision(False, "missing_pullback")

    pullback = pullbacks[-1]
    require_zone = _bool(params.get("require_zone"), True)
    zones_enabled = _bool(params.get("enable_operation_zones"), True)
    matching_zone = None
    if zones_enabled:
        matching_zone = next((zone for zone in operation_zones if zone.direction == "BUY" and is_candle_inside_operation_zone(confirmation, zone)), None)

    if require_zone and matching_zone is None:
        return TorumV1BuyDecision(False, "confirmation_outside_operation_zone", confirmation_time, pullback)

    metadata = {
        "symbol": symbol.upper(),
        "entry_timeframe": "M5",
        "confirmation_candle_time": confirmation_time_int,
        "pullback_pct": pullback.pullback_pct,
        "swing_high": pullback.swing_high,
        "pullback_low": pullback.pullback_low,
        "operation_zone_id": matching_zone.drawing_id if matching_zone else None,
    }
    return TorumV1BuyDecision(True, "buy_pullback_confirmed_inside_zone", confirmation_time, pullback, matching_zone, metadata)


def pullback_debug_payload(candles_m5: list[object], params: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = _float_param(params.get("pullback_threshold_pct"), 0.20)
    lookback = _int_param(params.get("pullback_lookback_bars"), 12)
    return [
        {
            "swing_high_time": int(pullback.swing_high_time.timestamp()),
            "swing_high": pullback.swing_high,
            "pullback_low_time": int(pullback.pullback_low_time.timestamp()),
            "pullback_low": pullback.pullback_low,
            "pullback_pct": pullback.pullback_pct,
            "label": f"PB > {threshold:.2f}% ({pullback.pullback_pct:.2f}%)",
        }
        for pullback in detect_pullbacks(candles_m5, threshold, lookback)
    ]


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
        params = _symbol_params(symbol, config)
        timeframe = _timeframe(params.get("timeframe"))
        session_start = _hhmm(params.get("session_start"), _default_session_start(symbol))
        session_end = _hhmm(params.get("session_end"), _default_session_end(symbol))
        enabled = bool(strategies_enabled and config is not None and config.enabled and _bool(params.get("enabled"), True))
        base = {
            "symbol": symbol,
            "enabled": enabled,
            "timeframe": timeframe,
            "session_start": session_start,
            "session_end": session_end,
            "active_config_id": config.id if config is not None else None,
        }

        if not strategies_enabled:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="engine_disabled", unlocked_at=None, blocked_by_news=False)
        if config is None:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="strategy_not_configured", unlocked_at=None, blocked_by_news=False)
        if not enabled:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="symbol_disabled", unlocked_at=None, blocked_by_news=False)

        if self._is_news_blocked(symbol, config, checked_at):
            return TorumV1AssetStatus(**base, status="LOCKED", reason="news_zone", unlocked_at=None, blocked_by_news=True)

        session_start_dt = _local_dt(madrid_now.date(), session_start)
        session_end_dt = _local_dt(madrid_now.date(), session_end)
        if madrid_now < session_start_dt or madrid_now >= session_end_dt:
            return TorumV1AssetStatus(**base, status="LOCKED", reason="outside_session", unlocked_at=None, blocked_by_news=False)

        unlocked_at, reason = self._unlocked_at(symbol, timeframe, madrid_now)
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

    def _unlocked_at(self, symbol: str, timeframe: str, madrid_now: datetime) -> tuple[datetime | None, str]:
        starts = _evaluation_starts(symbol, timeframe)
        duration = timedelta(hours=3 if timeframe == "H3" else 2)
        last_reason = "waiting_closed_candle"

        for start_label in starts:
            start_local = _local_dt(madrid_now.date(), start_label)
            end_local = start_local + duration
            if madrid_now < end_local:
                continue

            current = self._aggregate_window(symbol, start_local, end_local)
            previous = self._aggregate_window(symbol, start_local - duration, start_local)
            if current is None:
                last_reason = "missing_current_candle"
                continue

            if current.close > current.open:
                return end_local.astimezone(UTC), "bullish_closed_candle"
            if previous is not None and current.low >= previous.low:
                return end_local.astimezone(UTC), "held_previous_low"
            last_reason = "broke_previous_low"

        return None, last_reason

    def _aggregate_window(self, symbol: str, start_local: datetime, end_local: datetime) -> AggregatedCandle | None:
        start_utc = start_local.astimezone(UTC)
        end_utc = end_local.astimezone(UTC)
        for timeframe in ("M1", "M5", "H1", "H2", "H3"):
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


def _int_param(value: object, fallback: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else fallback


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


def _timeframe(value: object) -> str:
    candidate = str(value or "H2").upper()
    return candidate if candidate in SUPPORTED_EVALUATION_TIMEFRAMES else "H2"


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


def _evaluation_starts(symbol: str, timeframe: str) -> tuple[str, ...]:
    if symbol == "XAUEUR":
        return ("09:00", "11:00", "13:00") if timeframe == "H2" else ("09:00",)
    return ("15:00", "17:00", "19:00") if timeframe == "H2" else ("15:00", "18:00")


def _local_dt(day: object, hhmm: str) -> datetime:
    parsed = time.fromisoformat(hhmm)
    return datetime.combine(day, parsed, tzinfo=MADRID_TZ)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

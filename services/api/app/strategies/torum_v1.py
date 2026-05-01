from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
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

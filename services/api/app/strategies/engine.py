from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.core.config import get_settings
from app.core.decision_log import trace_event
from app.market_data.chart_clock import resolve_market_clock
from app.drawings.models import ChartDrawing
from app.indicators.engine import IndicatorEngine
from app.no_trade_zones.service import NoTradeZoneService
from app.orders.models import Order
from app.positions.models import Position
from app.strategies.context import StrategyContext
from app.strategies.models import StrategyConfig
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by


class StrategyContextBuilder:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(self, config: StrategyConfig, *, limit: int = 300) -> StrategyContext:
        started = perf_counter()
        params = config.params_json or {}
        entry_timeframe = str(params.get("entry_timeframe") or "M5").upper()
        candle_timeframe = entry_timeframe if config.strategy_key == "torum_v1" else config.timeframe
        candles = self._load_candles(config.internal_symbol, candle_timeframe, limit)
        latest_tick = self._latest_tick(config.internal_symbol)
        real_now = datetime.now(UTC)
        if config.strategy_key == "torum_v1":
            now, market_clock_domain = resolve_market_clock(
                real_now,
                latest_tick.time if latest_tick is not None else None,
            )
        else:
            now, market_clock_domain = real_now, "UTC"
        # Torum V1 performs DXY/news checks through dedicated cached services.
        # Loading 300 D1 candles and recalculating SMA/no-trade zones here put
        # irrelevant database work on the sub-second entry path.
        if config.strategy_key == "torum_v1":
            indicators: dict[str, object] = {}
            no_trade_zones: list[object] = []
        else:
            indicators = self._load_indicators()
            no_trade_zones = NoTradeZoneService(self.db).get_active_zones(config.internal_symbol)
        manual_zones = self._manual_zones(config)
        open_positions = self._open_positions(config)
        context = StrategyContext(
            strategy_key=config.strategy_key,
            config=config,
            symbol=config.internal_symbol,
            timeframe=config.timeframe,
            mode=config.mode,
            now=now,
            candles=candles,
            latest_tick=latest_tick,
            indicators=indicators,
            no_trade_zones=no_trade_zones,
            manual_zones=manual_zones,
            open_positions=open_positions,
            params=params,
        )
        recent_count = max(5, min(100, get_settings().strategy_trace_recent_candles))
        trace_event(
            "strategy_context",
            "context_built",
            strategy_key=config.strategy_key,
            config_id=config.id,
            config_revision=config.revision,
            user_id=config.user_id,
            symbol=config.internal_symbol,
            mode=config.mode,
            config_timeframe=config.timeframe,
            candle_timeframe=candle_timeframe,
            now=now,
            real_now_utc=real_now,
            market_clock_domain=market_clock_domain,
            candle_count=len(candles),
            first_candle_time=candles[0].time if candles else None,
            last_candle_time=candles[-1].time if candles else None,
            recent_candles=[
                {
                    "time": candle.time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "tick_count": candle.tick_count,
                }
                for candle in candles[-recent_count:]
            ],
            latest_tick={
                "time": latest_tick.time,
                "time_msc": latest_tick.time_msc,
                "bid": latest_tick.bid,
                "ask": latest_tick.ask,
                "last": latest_tick.last,
                "broker_symbol": latest_tick.broker_symbol,
            }
            if latest_tick is not None
            else None,
            manual_drawings=[
                {
                    "id": drawing.id,
                    "type": drawing.drawing_type,
                    "visible": drawing.visible,
                    "payload": drawing.payload_json,
                    "metadata": drawing.metadata_json,
                    "style": drawing.style_json,
                }
                for drawing in manual_zones
            ],
            no_trade_zones=[
                {
                    "id": zone.id,
                    "reason": zone.reason,
                    "start_time": zone.start_time,
                    "end_time": zone.end_time,
                    "blocks_trading": zone.blocks_trading,
                }
                for zone in no_trade_zones
            ],
            build_duration_ms=round((perf_counter() - started) * 1000.0, 3),
            open_positions=[
                {
                    "id": position.id,
                    "order_id": position.order_id,
                    "status": position.status,
                    "side": position.side,
                    "volume": position.volume,
                    "open_price": position.open_price,
                    "tp": position.tp,
                    "opened_at": position.opened_at,
                    "mt5_position_ticket": position.mt5_position_ticket,
                }
                for position in open_positions
            ],
        )
        return context

    def _load_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        rows = list(
            self.db.scalars(
                select(Candle)
                .where(Candle.internal_symbol == symbol, Candle.timeframe == timeframe)
                .order_by(Candle.time.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows

    def _latest_tick(self, symbol: str) -> Tick | None:
        return self.db.scalar(select(Tick).where(Tick.internal_symbol == symbol).order_by(*latest_tick_order_by()).limit(1))

    def _load_indicators(self) -> dict[str, object]:
        dxy_rows = self._load_candles("DXY", "D1", 300)
        latest_close = dxy_rows[-1].close if dxy_rows else None
        try:
            result = IndicatorEngine(self.db).calculate("SMA", "DXY", "D1", {"period": 30}, limit=300)
            points = result["output"].get("points", []) if isinstance(result.get("output"), dict) else []
            latest_sma = points[-1]["value"] if points else None
        except KeyError:
            latest_sma = None
        return {"dxy_sma30": {"latest_close": latest_close, "latest_sma": latest_sma}}

    def _manual_zones(self, config: StrategyConfig) -> list[ChartDrawing]:
        return list(
            self.db.scalars(
                select(ChartDrawing).where(
                    ChartDrawing.user_id == config.user_id,
                    ChartDrawing.internal_symbol == config.internal_symbol,
                    ChartDrawing.drawing_type.in_(("rectangle", "manual_zone", "horizontal_line")),
                    ChartDrawing.visible.is_(True),
                    ChartDrawing.source == "MANUAL",
                    ChartDrawing.deleted_at.is_(None),
                )
            )
        )

    def _open_positions(self, config: StrategyConfig) -> list[Position]:
        stmt = select(Position).where(
            Position.internal_symbol == config.internal_symbol,
            Position.status == "OPEN",
            Position.closed_at.is_(None),
            Position.close_price.is_(None),
            Position.mode == config.mode,
        )
        if config.user_id is not None:
            stmt = stmt.where(Position.user_id == config.user_id)
        if config.strategy_key == "torum_v1":
            stmt = stmt.join(Order, Position.order_id == Order.id).where(
                Order.source == "STRATEGY",
                Order.strategy_key == "torum_v1",
            )

        positions = list(self.db.scalars(stmt))
        return [
            position
            for position in positions
            if position.mode == "PAPER"
            or position.mt5_position_ticket is not None
            or position.mt5_position_identifier is not None
        ]

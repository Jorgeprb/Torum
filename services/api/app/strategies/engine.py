from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.indicators.engine import IndicatorEngine
from app.no_trade_zones.service import NoTradeZoneService
from app.positions.models import Position
from app.strategies.context import StrategyContext
from app.strategies.models import StrategyConfig
from app.ticks.models import Tick


class StrategyContextBuilder:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(self, config: StrategyConfig, *, limit: int = 300) -> StrategyContext:
        candles = self._load_candles(config.internal_symbol, config.timeframe, limit)
        latest_tick = self._latest_tick(config.internal_symbol)
        indicators = self._load_indicators()
        return StrategyContext(
            strategy_key=config.strategy_key,
            config=config,
            symbol=config.internal_symbol,
            timeframe=config.timeframe,
            mode=config.mode,
            now=datetime.now(UTC),
            candles=candles,
            latest_tick=latest_tick,
            indicators=indicators,
            no_trade_zones=NoTradeZoneService(self.db).get_active_zones(config.internal_symbol),
            manual_zones=self._manual_zones(config),
            open_positions=self._open_positions(config.internal_symbol),
            params=config.params_json or {},
        )

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
        return self.db.scalar(select(Tick).where(Tick.internal_symbol == symbol).order_by(Tick.time.desc(), Tick.id.desc()).limit(1))

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
                    ChartDrawing.drawing_type == "manual_zone",
                    ChartDrawing.visible.is_(True),
                    ChartDrawing.source == "MANUAL",
                    ChartDrawing.deleted_at.is_(None),
                )
            )
        )

    def _open_positions(self, symbol: str) -> list[Position]:
        return list(self.db.scalars(select(Position).where(Position.internal_symbol == symbol, Position.status == "OPEN")))

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_current_user
from app.alerts.service import PriceAlertService
from app.db.session import get_db
from app.drawings.service import ChartDrawingService
from app.indicators.schemas import ChartOverlaysResponse
from app.indicators.service import IndicatorService
from app.market_data.timeframes import Timeframe
from app.news.service import get_global_news_settings
from app.no_trade_zones.schemas import NoTradeZoneRead
from app.no_trade_zones.service import NoTradeZoneService
from app.positions.schemas import PositionRead
from app.positions.service import PositionService
from app.candles.models import Candle
from app.strategies.models import StrategyConfig
from app.strategies.torum_v1 import TORUM_V1_KEY, pullback_debug_payload
from app.users.models import User

router = APIRouter(prefix="/chart", tags=["chart"])

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

def _is_really_open_position(position: object) -> bool:
    status = getattr(position, "status", None)
    mode = getattr(position, "mode", None)
    closed_at = getattr(position, "closed_at", None)
    close_price = getattr(position, "close_price", None)
    mt5_position_ticket = getattr(position, "mt5_position_ticket", None)

    if status != "OPEN":
        return False

    if closed_at is not None:
        return False

    if close_price is not None:
        return False

    if mode != "PAPER" and mt5_position_ticket is None:
        return False

    return True

@router.get("/overlays", response_model=ChartOverlaysResponse)
def chart_overlays(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    symbol: str = Query(min_length=3),
    timeframe: Timeframe = Query(),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
) -> ChartOverlaysResponse:
    now = datetime.now(UTC)
    start = _as_utc(from_time) if from_time is not None else now - timedelta(days=30)
    end = _as_utc(to_time) if to_time is not None else now + timedelta(days=30)
    indicator_overlays = IndicatorService(db).calculate_active_overlays(symbol=symbol, timeframe=timeframe)
    news_settings = get_global_news_settings(db)
    no_trade_zones = []
    if news_settings.draw_news_zones_enabled:
        visible_zone_start = max(start, now)
        no_trade_zones = [
            NoTradeZoneRead.model_validate(zone).model_dump(mode="json")
            for zone in NoTradeZoneService(db).list_zones(symbol=symbol, start_time=visible_zone_start, end_time=end)
        ]
    drawing_service = ChartDrawingService(db)
    drawings = [
        drawing_service.to_read(drawing).model_dump(mode="json")
        for drawing in drawing_service.list_visible_for_overlays(user=current_user, symbol=symbol, timeframe=timeframe)
    ]
    price_alerts = []
    if current_user is not None:
        alert_service = PriceAlertService(db)
        price_alerts = [
            alert_service.to_read(alert).model_dump(mode="json")
            for alert in alert_service.list_for_user(user=current_user, symbol=symbol, status_filter="ACTIVE")
        ]
    positions = [
    PositionRead.model_validate(position).model_dump(mode="json")
        for position in PositionService(db).list_with_prices(status="OPEN", symbol=symbol, limit=200)
        if _is_really_open_position(position)
    ]
    strategy_debug_pullbacks = []
    if current_user is not None:
        config = (
            db.query(StrategyConfig)
            .filter(
                StrategyConfig.user_id == current_user.id,
                StrategyConfig.strategy_key == TORUM_V1_KEY,
                StrategyConfig.internal_symbol == symbol.upper(),
                StrategyConfig.enabled.is_(True),
            )
            .order_by(StrategyConfig.id)
            .first()
        )
        params = config.params_json if config is not None else {}
        if config is not None and bool(params.get("show_pullback_debug", False)):
            candles_m5 = list(
                db.query(Candle)
                .filter(
                    Candle.internal_symbol == symbol.upper(),
                    Candle.timeframe == "M5",
                    Candle.time >= start,
                    Candle.time <= end,
                )
                .order_by(Candle.time)
            )
            strategy_debug_pullbacks = pullback_debug_payload(candles_m5, params)
    return ChartOverlaysResponse(
        symbol=symbol.upper(),
        timeframe=timeframe,
        indicators=indicator_overlays,
        no_trade_zones=no_trade_zones,
        drawings=drawings,
        price_alerts=price_alerts,
        positions=positions,
        strategy_debug_pullbacks=strategy_debug_pullbacks,
    )

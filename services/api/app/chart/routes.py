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
from app.no_trade_zones.schemas import NoTradeZoneRead
from app.no_trade_zones.service import NoTradeZoneService
from app.users.models import User

router = APIRouter(prefix="/chart", tags=["chart"])


@router.get("/overlays", response_model=ChartOverlaysResponse)
def chart_overlays(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    symbol: str = Query(min_length=3),
    timeframe: Timeframe = Query(),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
) -> ChartOverlaysResponse:
    start = from_time or datetime.now(UTC) - timedelta(days=30)
    end = to_time or datetime.now(UTC) + timedelta(days=30)
    indicator_overlays = IndicatorService(db).calculate_active_overlays(symbol=symbol, timeframe=timeframe)
    no_trade_zones = [
        NoTradeZoneRead.model_validate(zone).model_dump(mode="json")
        for zone in NoTradeZoneService(db).list_zones(symbol=symbol, start_time=start, end_time=end)
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
    return ChartOverlaysResponse(
        symbol=symbol.upper(),
        timeframe=timeframe,
        indicators=indicator_overlays,
        no_trade_zones=no_trade_zones,
        drawings=drawings,
        price_alerts=price_alerts,
    )

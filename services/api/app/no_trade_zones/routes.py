from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.news.service import NewsService, get_global_news_settings
from app.no_trade_zones.repository import get_zone
from app.no_trade_zones.schemas import (
    NoTradeZoneCheckResponse,
    NoTradeZoneRead,
    NoTradeZoneRegenerateResponse,
    NoTradeZoneUpdate,
)
from app.no_trade_zones.service import NoTradeZoneService
from app.users.models import User

router = APIRouter(prefix="/no-trade-zones", tags=["no-trade-zones"])


@router.get("", response_model=list[NoTradeZoneRead])
def list_no_trade_zones(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None, min_length=3),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    include_disabled: bool = False,
) -> list[NoTradeZoneRead]:
    start = from_time or datetime.now(UTC) - timedelta(days=14)
    end = to_time or datetime.now(UTC) + timedelta(days=14)
    return [
        NoTradeZoneRead.model_validate(zone)
        for zone in NoTradeZoneService(db).list_zones(
            symbol=symbol,
            start_time=start,
            end_time=end,
            include_disabled=include_disabled,
        )
    ]


@router.post("/regenerate", response_model=NoTradeZoneRegenerateResponse)
def regenerate_zones(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NoTradeZoneRegenerateResponse:
    return NoTradeZoneRegenerateResponse(regenerated=NewsService(db).regenerate_zones())


@router.patch("/{zone_id}", response_model=NoTradeZoneRead)
def patch_zone(
    zone_id: int,
    payload: NoTradeZoneUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> NoTradeZoneRead:
    zone = get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No trade zone not found")
    try:
        updated = NoTradeZoneService(db).update_zone(zone, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NoTradeZoneRead.model_validate(updated)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    zone = get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No trade zone not found")
    NoTradeZoneService(db).delete_zone(zone)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/check", response_model=NoTradeZoneCheckResponse)
def check_zone(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(min_length=3),
    time: datetime | None = None,
) -> NoTradeZoneCheckResponse:
    checked_at = time or datetime.now(UTC)
    settings = get_global_news_settings(db)
    active_zones = NoTradeZoneService(db).get_active_zones(symbol, checked_at)
    blocked = settings.block_trading_during_news and any(zone.blocks_trading for zone in active_zones)
    return NoTradeZoneCheckResponse(
        blocked=blocked,
        symbol=symbol.upper(),
        time=checked_at,
        zones=[NoTradeZoneRead.model_validate(zone) for zone in active_zones],
    )

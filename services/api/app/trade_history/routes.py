from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.positions.models import Position
from app.trade_history.schemas import TradeHistoryItem
from app.users.models import User

router = APIRouter(prefix="/trade-history", tags=["trade-history"])


@router.get("", response_model=list[TradeHistoryItem])
def list_trade_history(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TradeHistoryItem]:
    stmt = select(Position).order_by(Position.opened_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(Position.internal_symbol == symbol.upper())
    if mode:
        stmt = stmt.where(Position.mode == mode.upper())
    if status_filter:
        stmt = stmt.where(Position.status == status_filter.upper())
    if from_time:
        stmt = stmt.where(Position.opened_at >= from_time)
    if to_time:
        stmt = stmt.where(Position.opened_at <= to_time)
    return [_to_history_item(position) for position in db.scalars(stmt)]


@router.get("/{position_id}", response_model=TradeHistoryItem)
def get_trade_history_item(
    position_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TradeHistoryItem:
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade history item not found")
    return _to_history_item(position)


def _to_history_item(position: Position) -> TradeHistoryItem:
    return TradeHistoryItem(
        id=position.id,
        position_id=position.id,
        order_id=position.order_id,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        internal_symbol=position.internal_symbol,
        broker_symbol=position.broker_symbol,
        side=position.side,
        volume=position.volume,
        open_price=position.open_price,
        close_price=position.close_price if position.status == "CLOSED" else None,
        tp=position.tp,
        profit=position.profit,
        swap=position.swap,
        commission=position.commission,
        mode=position.mode,
        mt5_position_ticket=position.mt5_position_ticket,
        closing_deal_ticket=position.closing_deal_ticket,
        status=position.status,
    )

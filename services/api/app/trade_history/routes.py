from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.positions.models import Position
from app.trade_history.schemas import TradeHistoryItem
from app.users.models import User, UserRole

router = APIRouter(prefix="/trade-history", tags=["trade-history"])


def _fee_from_payload(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("fee")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _payload_fee(position: Position) -> float | None:
    if position.fee is not None:
        return float(position.fee)
    fee = _fee_from_payload(position.close_payload_json)
    if fee is not None:
        return fee

    raw_payload = position.raw_payload_json
    if isinstance(raw_payload, dict):
        close_deal = raw_payload.get("close_deal")
        fee = _fee_from_payload(close_deal)
        if fee is not None:
            return fee
    return None


@router.get("", response_model=list[TradeHistoryItem])
def list_trade_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    account_login: int | None = Query(default=None),
    account_server: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TradeHistoryItem]:
    stmt = select(Position)
    if current_user.role != UserRole.admin:
        stmt = stmt.where(Position.user_id == current_user.id)
    if symbol:
        stmt = stmt.where(Position.internal_symbol == symbol.upper())
    if mode:
        stmt = stmt.where(Position.mode == mode.upper())
    if status_filter:
        stmt = stmt.where(Position.status == status_filter.upper())
    if account_login is not None:
        stmt = stmt.where(Position.account_login == account_login)
    if account_server:
        stmt = stmt.where(Position.account_server == account_server)
    if from_time:
        stmt = stmt.where(Position.opened_at >= from_time)
    if to_time:
        stmt = stmt.where(Position.opened_at <= to_time)
    if status_filter and status_filter.upper() == "CLOSED":
        stmt = stmt.order_by(Position.closed_at.desc().nullslast(), Position.opened_at.desc())
    else:
        stmt = stmt.order_by(Position.opened_at.desc())
    stmt = stmt.limit(limit)
    return [_to_history_item(position) for position in db.scalars(stmt)]


@router.get("/{position_id}", response_model=TradeHistoryItem)
def get_trade_history_item(
    position_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TradeHistoryItem:
    position = db.get(Position, position_id)
    if position is None or (current_user.role != UserRole.admin and position.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade history item not found")
    return _to_history_item(position)


def _to_history_item(position: Position) -> TradeHistoryItem:
    return TradeHistoryItem(
        id=position.id,
        position_id=position.id,
        order_id=position.order_id,
        account_login=position.account_login,
        account_server=position.account_server,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        open_time_msc=position.open_time_msc,
        close_time_msc=position.close_time_msc,
        enrichment_status=position.enrichment_status,
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
        fee=_payload_fee(position),
        net_profit=position.net_profit,
        mode=position.mode,
        mt5_position_ticket=position.mt5_position_ticket,
        closing_deal_ticket=position.closing_deal_ticket,
        status=position.status,
    )

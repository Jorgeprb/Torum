from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.orders.repository import get_order, list_orders
from app.orders.schemas import OrderRead
from app.orders.service import OrderManager
from app.trading.schemas import ManualOrderRequest, ManualOrderResponse
from app.users.models import User

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/manual", response_model=ManualOrderResponse, status_code=status.HTTP_201_CREATED)
def create_manual_order(
    payload: ManualOrderRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManualOrderResponse:
    return OrderManager(db).create_manual_order(payload, current_user)


@router.get("", response_model=list[OrderRead])
def get_orders(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[OrderRead]:
    return [OrderRead.model_validate(order) for order in list_orders(db, limit=limit)]


@router.get("/{order_id}", response_model=OrderRead)
def get_order_by_id(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> OrderRead:
    order = get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderRead.model_validate(order)

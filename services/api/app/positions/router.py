from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.positions.schemas import PositionCloseRequest, PositionRead, PositionTpUpdate
from app.positions.service import PositionService
from app.users.models import User

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionRead])
def get_positions(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    status_filter: str | None = Query(default=None, alias="status"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PositionRead]:
    return [
        PositionRead.model_validate(position)
        for position in PositionService(db).list_with_prices(status_filter, limit, symbol)
    ]


@router.post("/{position_id}/close", response_model=PositionRead)
def close_position(
    position_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    payload: PositionCloseRequest | None = None,
) -> PositionRead:
    if payload and payload.client_confirmation and payload.client_confirmation.get("confirmed") is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Close confirmation is required")
    ok, message, position = PositionService(db).close_position(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return PositionRead.model_validate(position)


@router.patch("/{position_id}/tp", response_model=PositionRead)
def modify_position_tp(
    position_id: int,
    payload: PositionTpUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> PositionRead:
    ok, message, position = PositionService(db).modify_take_profit(position_id, payload.tp)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return PositionRead.model_validate(position)

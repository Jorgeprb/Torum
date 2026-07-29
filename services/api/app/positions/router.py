from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.positions.models import Position
from app.positions.schemas import PositionCloseRequest, PositionRead, PositionTpUpdate
from app.positions.service import PositionService
from app.users.models import User, UserRole

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionRead])
def get_positions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    status_filter: str | None = Query(default=None, alias="status"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PositionRead]:
    return [
        PositionRead.model_validate(position)
        for position in PositionService(db).list_with_prices(
            status_filter,
            limit,
            symbol,
            user_id=current_user.id,
            include_all_users=current_user.role == UserRole.admin,
        )
    ]


@router.post("/reconcile-mt5")
def reconcile_mt5_positions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, int]:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return PositionService(db).reconcile_missing_mt5_positions()


@router.post("/{position_id}/close", response_model=PositionRead)
def close_position(
    position_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    payload: PositionCloseRequest | None = None,
) -> PositionRead:
    if payload and payload.client_confirmation and payload.client_confirmation.get("confirmed") is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Close confirmation is required")
    existing = db.get(Position, position_id)
    if existing is None or (current_user.role != UserRole.admin and existing.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    ok, message, position = PositionService(db, background_tasks=background_tasks).close_position(
        position_id,
        fetch_close_deal=bool(payload.fetch_close_deal) if payload else False,
    )
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return PositionRead.model_validate(position)


@router.patch("/{position_id}/tp", response_model=PositionRead)
def modify_position_tp(
    position_id: int,
    payload: PositionTpUpdate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PositionRead:
    existing = db.get(Position, position_id)
    if existing is None or (current_user.role != UserRole.admin and existing.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    ok, message, position = PositionService(db, background_tasks=background_tasks).modify_take_profit(position_id, payload.tp)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return PositionRead.model_validate(position)

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.performance.schemas import CapitalMovementCreate, CapitalMovementRead, PerformanceSummary
from app.performance.service import PerformanceService
from app.users.models import User

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("", response_model=PerformanceSummary)
def get_performance(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    from_time: datetime = Query(alias="from"),
    to_time: datetime = Query(alias="to"),
) -> PerformanceSummary:
    try:
        return PerformanceService(db).report(current_user, from_time=from_time, to_time=to_time)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/capital-movements", response_model=list[CapitalMovementRead])
def list_capital_movements(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[CapitalMovementRead]:
    service = PerformanceService(db)
    return [service._movement_read(item, current_user) for item in service.list_movements(current_user, limit=limit)]


@router.post("/capital-movements", response_model=CapitalMovementRead, status_code=status.HTTP_201_CREATED)
def create_capital_movement(
    payload: CapitalMovementCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CapitalMovementRead:
    service = PerformanceService(db)
    try:
        movement = service.create_manual_movement(current_user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return service._movement_read(movement, current_user)


@router.delete("/capital-movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capital_movement(
    movement_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if not PerformanceService(db).delete_manual_movement(current_user, movement_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capital movement not found or read-only")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

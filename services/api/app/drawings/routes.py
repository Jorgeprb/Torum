from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.drawings.repository import get_drawing
from app.drawings.schemas import ChartDrawingBulkCreate, ChartDrawingCreate, ChartDrawingRead, ChartDrawingUpdate
from app.drawings.service import ChartDrawingService
from app.market_data.timeframes import Timeframe
from app.users.models import User

router = APIRouter(prefix="/drawings", tags=["drawings"])


@router.get("", response_model=list[ChartDrawingRead])
def list_chart_drawings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(min_length=3),
    timeframe: Timeframe = Query(),
    include_hidden: bool = False,
) -> list[ChartDrawingRead]:
    service = ChartDrawingService(db)
    return [
        service.to_read(drawing)
        for drawing in service.list_for_user(
            user=current_user,
            symbol=symbol,
            timeframe=timeframe,
            include_hidden=include_hidden,
        )
    ]


@router.post("", response_model=ChartDrawingRead, status_code=status.HTTP_201_CREATED)
def create_chart_drawing(
    payload: ChartDrawingCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChartDrawingRead:
    service = ChartDrawingService(db)
    return service.to_read(service.create(payload, current_user))


@router.post("/bulk", response_model=list[ChartDrawingRead], status_code=status.HTTP_201_CREATED)
def create_chart_drawings_bulk(
    payload: ChartDrawingBulkCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ChartDrawingRead]:
    service = ChartDrawingService(db)
    created = [service.create(item, current_user) for item in payload.items]
    return [service.to_read(item) for item in created]


@router.patch("/{drawing_id}", response_model=ChartDrawingRead)
def update_chart_drawing(
    drawing_id: str,
    payload: ChartDrawingUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChartDrawingRead:
    drawing = get_drawing(db, drawing_id)
    if drawing is None or drawing.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")
    service = ChartDrawingService(db)
    return service.to_read(service.update(drawing, payload, current_user))


@router.delete("/{drawing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chart_drawing(
    drawing_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    drawing = get_drawing(db, drawing_id)
    if drawing is None or drawing.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")
    ChartDrawingService(db).soft_delete(drawing, current_user)

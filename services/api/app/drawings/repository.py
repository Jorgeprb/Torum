from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drawings.models import ChartDrawing


def get_drawing(db: Session, drawing_id: str) -> ChartDrawing | None:
    return db.get(ChartDrawing, drawing_id)


def list_drawings(
    db: Session,
    *,
    user_id: int | None,
    symbol: str,
    timeframe: str | None = None,
    include_hidden: bool = False,
    visible_only: bool = False,
) -> list[ChartDrawing]:
    del timeframe  # Drawings are anchored to time/price and are visible across timeframes.
    stmt = select(ChartDrawing).where(
        ChartDrawing.internal_symbol == symbol.upper(),
        ChartDrawing.deleted_at.is_(None),
    )
    if user_id is not None:
        stmt = stmt.where(ChartDrawing.user_id == user_id)
    if visible_only or not include_hidden:
        stmt = stmt.where(ChartDrawing.visible.is_(True))
    return list(db.scalars(stmt.order_by(ChartDrawing.created_at, ChartDrawing.id)))

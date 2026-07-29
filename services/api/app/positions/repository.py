from sqlalchemy import select
from sqlalchemy.orm import Session

from app.positions.models import Position


def list_positions(
    db: Session,
    status: str | None = None,
    limit: int = 100,
    symbol: str | None = None,
    *,
    user_id: int | None = None,
    include_all_users: bool = True,
) -> list[Position]:
    stmt = select(Position).order_by(Position.opened_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Position.status == status)
    if symbol:
        stmt = stmt.where(Position.internal_symbol == symbol.upper())
    if not include_all_users:
        stmt = stmt.where(Position.user_id == user_id)
    return list(db.scalars(stmt))


def get_position(db: Session, position_id: int) -> Position | None:
    return db.get(Position, position_id)

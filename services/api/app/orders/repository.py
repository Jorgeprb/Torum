from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orders.models import Order


def list_orders(db: Session, limit: int = 100) -> list[Order]:
    return list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(limit)))


def get_order(db: Session, order_id: int) -> Order | None:
    return db.get(Order, order_id)

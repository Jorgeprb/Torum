from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orders.models import Order


def list_orders(
    db: Session,
    limit: int = 100,
    *,
    user_id: int | None = None,
    include_all_users: bool = True,
    account_login: int | None = None,
    account_server: str | None = None,
) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
    if not include_all_users:
        stmt = stmt.where(Order.user_id == user_id)
    if account_login is not None:
        stmt = stmt.where(Order.account_login == account_login)
    if account_server:
        stmt = stmt.where(Order.account_server == account_server)
    return list(db.scalars(stmt))


def get_order(
    db: Session,
    order_id: int,
    *,
    user_id: int | None = None,
    include_all_users: bool = True,
) -> Order | None:
    order = db.get(Order, order_id)
    if order is None:
        return None
    if not include_all_users and order.user_id != user_id:
        return None
    return order

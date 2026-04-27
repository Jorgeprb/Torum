from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import PriceAlert, PushSubscription


def get_price_alert(db: Session, alert_id: str) -> PriceAlert | None:
    return db.get(PriceAlert, alert_id)


def list_price_alerts(
    db: Session,
    *,
    user_id: int,
    symbol: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    limit: int = 200,
) -> list[PriceAlert]:
    stmt = select(PriceAlert).where(PriceAlert.user_id == user_id)
    if symbol:
        stmt = stmt.where(PriceAlert.internal_symbol == symbol.upper())
    if status:
        stmt = stmt.where(PriceAlert.status == status.upper())
    if not include_deleted:
        stmt = stmt.where(PriceAlert.deleted_at.is_(None))
    stmt = stmt.order_by(PriceAlert.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def list_active_alerts_for_symbol(db: Session, symbol: str) -> list[PriceAlert]:
    return list(
        db.scalars(
            select(PriceAlert)
            .where(
                PriceAlert.internal_symbol == symbol.upper(),
                PriceAlert.status == "ACTIVE",
                PriceAlert.deleted_at.is_(None),
            )
            .order_by(PriceAlert.target_price.desc())
        )
    )


def get_push_subscription(db: Session, subscription_id: str) -> PushSubscription | None:
    return db.get(PushSubscription, subscription_id)


def get_push_subscription_by_endpoint(db: Session, *, user_id: int, endpoint: str) -> PushSubscription | None:
    return db.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
    )


def list_push_subscriptions(db: Session, *, user_id: int, enabled_only: bool = False) -> list[PushSubscription]:
    stmt = select(PushSubscription).where(PushSubscription.user_id == user_id)
    if enabled_only:
        stmt = stmt.where(PushSubscription.enabled.is_(True))
    return list(db.scalars(stmt.order_by(PushSubscription.created_at.desc())))

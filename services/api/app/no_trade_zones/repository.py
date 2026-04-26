from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.no_trade_zones.models import NoTradeZone


def get_zone(db: Session, zone_id: int) -> NoTradeZone | None:
    return db.get(NoTradeZone, zone_id)


def list_zones(
    db: Session,
    symbol: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    include_disabled: bool = False,
    limit: int = 1000,
) -> list[NoTradeZone]:
    conditions = []
    if symbol:
        conditions.append(NoTradeZone.internal_symbol == symbol.upper())
    if start_time is not None:
        conditions.append(NoTradeZone.end_time >= start_time)
    if end_time is not None:
        conditions.append(NoTradeZone.start_time <= end_time)
    if not include_disabled:
        conditions.append(NoTradeZone.enabled.is_(True))

    stmt = select(NoTradeZone)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(NoTradeZone.start_time).limit(limit)
    return list(db.scalars(stmt))

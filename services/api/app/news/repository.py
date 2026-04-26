from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.news.models import NewsEvent, NewsSettings


def get_news_settings(db: Session) -> NewsSettings | None:
    return db.scalar(select(NewsSettings).where(NewsSettings.user_id.is_(None)))


def get_news_event(db: Session, event_id: int) -> NewsEvent | None:
    return db.get(NewsEvent, event_id)


def list_news_events(
    db: Session,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    currency: str | None = None,
    impact: str | None = None,
    limit: int = 500,
) -> list[NewsEvent]:
    conditions = []
    if start_time is not None:
        conditions.append(NewsEvent.event_time >= start_time)
    if end_time is not None:
        conditions.append(NewsEvent.event_time <= end_time)
    if currency:
        conditions.append(NewsEvent.currency == currency.upper())
    if impact:
        conditions.append(NewsEvent.impact == impact.upper())

    stmt = select(NewsEvent)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(NewsEvent.event_time).limit(limit)
    return list(db.scalars(stmt))

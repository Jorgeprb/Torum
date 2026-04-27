from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.tick_time import tick_time_msc_from_datetime
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by


class LatestTickRead(BaseModel):
    symbol: str
    internal_symbol: str
    broker_symbol: str
    source: str
    time: datetime
    time_msc: int
    bid: float | None
    ask: float | None
    last: float | None
    mid: float | None
    spread: float | None
    age_ms: int
    created_at: datetime


def latest_tick_for_symbol(db: Session, symbol: str) -> Tick | None:
    return db.scalar(
        select(Tick)
        .where(Tick.internal_symbol == symbol.upper())
        .order_by(*latest_tick_order_by())
        .limit(1)
    )


def latest_tick_to_read(tick: Tick) -> LatestTickRead:
    bid = tick.bid
    ask = tick.ask
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread = ask - bid if bid is not None and ask is not None else None
    now = datetime.now(UTC)
    tick_time = tick.time if tick.time.tzinfo else tick.time.replace(tzinfo=UTC)
    tick_time = tick_time.astimezone(UTC)
    return LatestTickRead(
        symbol=tick.internal_symbol,
        internal_symbol=tick.internal_symbol,
        broker_symbol=tick.broker_symbol,
        source=tick.source,
        time=tick_time,
        time_msc=tick.time_msc or tick_time_msc_from_datetime(tick_time),
        bid=bid,
        ask=ask,
        last=tick.last,
        mid=mid,
        spread=spread,
        age_ms=max(0, int((now - tick_time).total_seconds() * 1000)),
        created_at=tick.created_at,
    )

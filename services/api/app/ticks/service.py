from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.candles.service import CandleAggregator
from app.market_data.timeframes import ensure_utc
from app.symbols.service import enabled_internal_symbols
from app.ticks.models import Tick
from app.ticks.schemas import TickBatchRequest


class TickIngestionError(ValueError):
    pass


def tick_request_to_rows(db: Session, payload: TickBatchRequest) -> list[dict[str, object]]:
    enabled_symbols = enabled_internal_symbols(db)
    rows: list[dict[str, object]] = []

    for tick in payload.ticks:
        internal_symbol = tick.resolved_internal_symbol
        if internal_symbol not in enabled_symbols:
            raise TickIngestionError(f"Unknown or disabled internal symbol: {internal_symbol}")

        tick_source = tick.source or payload.source
        rows.append(
            {
                "time": ensure_utc(tick.time),
                "internal_symbol": internal_symbol,
                "broker_symbol": tick.broker_symbol,
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "volume": tick.volume or 0.0,
                "source": tick_source,
            }
        )

    return rows


def ingest_tick_batch(db: Session, payload: TickBatchRequest) -> tuple[int, int, list[Candle], list[dict[str, object]]]:
    rows = tick_request_to_rows(db, payload)
    if not rows:
        return 0, 0, [], []

    stmt = pg_insert(Tick).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            Tick.internal_symbol,
            Tick.broker_symbol,
            Tick.time,
            Tick.bid,
            Tick.ask,
            Tick.last,
        ]
    )
    stmt = stmt.returning(
        Tick.time,
        Tick.internal_symbol,
        Tick.broker_symbol,
        Tick.bid,
        Tick.ask,
        Tick.last,
        Tick.volume,
        Tick.source,
    )
    inserted_rows = [dict(row._mapping) for row in db.execute(stmt)]
    candles = CandleAggregator(db).aggregate_ticks(inserted_rows)
    db.commit()
    return len(rows), len(inserted_rows), candles, inserted_rows


def get_recent_ticks(db: Session, symbol: str, limit: int) -> list[Tick]:
    rows = list(
        db.scalars(
            select(Tick)
            .where(Tick.internal_symbol == symbol)
            .order_by(Tick.time.desc(), Tick.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return rows


def last_tick_time(db: Session) -> datetime | None:
    return db.scalar(select(Tick.time).order_by(Tick.time.desc()).limit(1))

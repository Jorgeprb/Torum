from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.candles.schemas import CandleRead
from app.candles.service import candle_to_read
from app.db.session import get_db
from app.market_data.timeframes import Timeframe

router = APIRouter(prefix="/candles", tags=["candles"])


@router.get("", response_model=list[CandleRead])
def get_candles(
    db: Annotated[Session, Depends(get_db)],
    symbol: str = Query(min_length=3),
    timeframe: Timeframe = Query(),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[CandleRead]:
    rows = list(
        db.scalars(
            select(Candle)
            .where(Candle.internal_symbol == symbol, Candle.timeframe == timeframe)
            .order_by(Candle.time.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return [candle_to_read(candle) for candle in rows]

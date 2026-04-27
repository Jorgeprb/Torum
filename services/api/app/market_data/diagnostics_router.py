from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.diagnostics import LatestTickRead, latest_tick_for_symbol, latest_tick_to_read

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/latest-tick", response_model=LatestTickRead)
def get_latest_tick(
    db: Annotated[Session, Depends(get_db)],
    symbol: str = Query(default="XAUUSD", min_length=3, max_length=32),
) -> LatestTickRead:
    tick = latest_tick_for_symbol(db, symbol)
    if tick is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No tick found for {symbol.upper()}")
    return latest_tick_to_read(tick)

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.positions.service import PositionService
from app.settings.trading_service import get_global_trading_settings, update_global_trading_settings
from app.mt5.status_store import mt5_status_store
from app.trading.lot_sizing import calculate_lot_size
from app.trading.schemas import LotSizeResponse, TradingSettingsRead, TradingSettingsUpdate
from app.users.models import User

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("/settings", response_model=TradingSettingsRead)
def get_trading_settings(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TradingSettingsRead:
    return TradingSettingsRead.model_validate(get_global_trading_settings(db))


@router.patch("/settings", response_model=TradingSettingsRead)
def patch_trading_settings(
    payload: TradingSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TradingSettingsRead:
    return TradingSettingsRead.model_validate(update_global_trading_settings(db, payload))


@router.get("/lot-size", response_model=LotSizeResponse)
def get_lot_size(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = "XAUUSD",
    multiplier: int = 1,
) -> LotSizeResponse:
    del symbol
    settings = get_global_trading_settings(db)
    account = mt5_status_store.get().account
    available_equity = account.margin_free if account and account.margin_free is not None else account.equity if account else None
    calculation = calculate_lot_size(
        available_equity=available_equity,
        equity_per_0_01_lot=settings.equity_per_0_01_lot,
        minimum_lot=settings.minimum_lot,
        multiplier=multiplier,
        enabled=settings.lot_per_equity_enabled,
    )
    return LotSizeResponse(**calculation.__dict__)


@router.post("/pause", response_model=TradingSettingsRead)
def pause_trading(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TradingSettingsRead:
    return TradingSettingsRead.model_validate(update_global_trading_settings(db, TradingSettingsUpdate(is_paused=True)))


@router.post("/resume", response_model=TradingSettingsRead)
def resume_trading(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TradingSettingsRead:
    return TradingSettingsRead.model_validate(update_global_trading_settings(db, TradingSettingsUpdate(is_paused=False)))


@router.post("/close-all")
def close_all(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    settings = get_global_trading_settings(db)
    if settings.trading_mode != "PAPER":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="close-all for DEMO/LIVE will be completed after MT5 position sync is hardened",
        )
    closed = PositionService(db).close_all_paper()
    return {"ok": True, "closed_positions": closed, "mode": "PAPER"}

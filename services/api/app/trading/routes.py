from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.positions.service import PositionService
from app.settings.trading_service import get_global_trading_settings, update_global_trading_settings
from app.mt5.status_store import mt5_status_store
from app.trading.lot_sizing import calculate_lot_size
from app.trading.schemas import MT5OrderExecutionSettingsRead, LotSizeResponse, TradingSettingsRead, TradingSettingsUpdate
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
    if payload.mt5_order_execution_enabled is True:
        try:
            MT5BridgeClient().set_order_execution_enabled(
                True,
                allowed_account_modes=["DEMO", "REAL"],
                enable_real_trading=True,
            )
        except MT5BridgeClientError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No se pudo activar ejecucion MT5 en el bridge: {exc}",
            ) from exc
    elif payload.mt5_order_execution_enabled is False:
        try:
            MT5BridgeClient().set_order_execution_enabled(False)
        except MT5BridgeClientError:
            # Turning the local guard off remains safe even if the bridge is down.
            pass
    return TradingSettingsRead.model_validate(update_global_trading_settings(db, payload))


@router.get("/mt5-order-execution", response_model=MT5OrderExecutionSettingsRead)
def get_mt5_order_execution(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> MT5OrderExecutionSettingsRead:
    settings = get_global_trading_settings(db)
    client = MT5BridgeClient()
    if not client.is_configured():
        return MT5OrderExecutionSettingsRead(
            torum_enabled=settings.mt5_order_execution_enabled,
            bridge_configured=False,
            bridge_connected=False,
            bridge_message="MT5 bridge base URL is not configured",
        )
    try:
        bridge_settings = client.get_order_execution_settings()
    except MT5BridgeClientError as exc:
        return MT5OrderExecutionSettingsRead(
            torum_enabled=settings.mt5_order_execution_enabled,
            bridge_configured=True,
            bridge_connected=False,
            bridge_message=str(exc),
        )
    return MT5OrderExecutionSettingsRead(
        torum_enabled=settings.mt5_order_execution_enabled,
        bridge_configured=True,
        bridge_connected=True,
        bridge_enabled=bool(bridge_settings.get("enabled")),
        bridge_message=str(bridge_settings.get("message") or ""),
    )


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

    # IMPORTANTE:
    # El lotaje base se calcula sobre BALANCE, no sobre equity ni margin_free.
    # Así las operaciones abiertas no modifican el tamaño base del lote.
    available_balance = account.balance if account and account.balance is not None else None

    calculation = calculate_lot_size(
        available_equity=available_balance,
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

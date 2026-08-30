from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
import logging
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.service_auth import require_service_token
from app.db.session import get_db
from app.mt5.account_service import SavedMT5AccountService
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.schemas import (
    MT5AccountPayload,
    MT5AccountSwitchRead,
    MT5DiscoveredAccountRead,
    MT5PositionsSyncPayload,
    MT5PositionsSyncRead,
    MT5StatusPayload,
    MT5StatusRead,
    SavedMT5AccountCreate,
    SavedMT5AccountRead,
    SavedMT5AccountUpdate,
)
from app.mt5.status_store import mt5_status_store
from app.positions.service import PositionService
from app.performance.service import PerformanceService
from app.risk.snapshot import RiskSnapshotService
from app.websockets.manager import market_ws_manager
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mt5", tags=["mt5"])


@router.get("/status", response_model=MT5StatusRead)
def get_mt5_status() -> MT5StatusRead:
    return mt5_status_store.get()


@router.get("/accounts", response_model=list[SavedMT5AccountRead])
def list_saved_mt5_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavedMT5AccountRead]:
    return SavedMT5AccountService(db).list_for_user(current_user, mt5_status_store.get().account)


@router.get("/accounts/discover", response_model=list[MT5DiscoveredAccountRead])
def discover_mt5_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MT5DiscoveredAccountRead]:
    try:
        discovered = MT5BridgeClient(timeout=15.0).discover_accounts()
    except MT5BridgeClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se pudieron consultar las cuentas del terminal MT5: {exc}",
        ) from exc

    saved_rows = SavedMT5AccountService(db).list_for_user(current_user, mt5_status_store.get().account)
    saved_keys = {(item.login, item.server.strip().casefold()) for item in saved_rows}
    result: list[MT5DiscoveredAccountRead] = []
    seen: set[tuple[int, str]] = set()
    for raw in discovered:
        try:
            login = int(raw.get("login"))
        except (TypeError, ValueError):
            continue
        server = str(raw.get("server") or "").strip()
        if login <= 0 or not server:
            continue
        key = (login, server.casefold())
        if key in seen:
            continue
        seen.add(key)
        source = "CURRENT" if str(raw.get("source") or "").upper() == "CURRENT" else "TERMINAL_DATA"
        result.append(
            MT5DiscoveredAccountRead(
                login=login,
                server=server,
                active=bool(raw.get("active")),
                already_saved=key in saved_keys,
                source=source,
            )
        )
    result.sort(key=lambda item: (not item.active, item.server.casefold(), item.login))
    return result


@router.post("/accounts", response_model=SavedMT5AccountRead, status_code=status.HTTP_201_CREATED)
def create_saved_mt5_account(
    payload: SavedMT5AccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedMT5AccountRead:
    active = mt5_status_store.get().account
    service = SavedMT5AccountService(db)
    row = service.create(current_user, payload, active)
    return service.to_read(row, active)


@router.patch("/accounts/{account_id}", response_model=SavedMT5AccountRead)
def rename_saved_mt5_account(
    account_id: int,
    payload: SavedMT5AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedMT5AccountRead:
    service = SavedMT5AccountService(db)
    row = service.rename(current_user, account_id, payload.alias)
    return service.to_read(row, mt5_status_store.get().account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_mt5_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    SavedMT5AccountService(db).delete(current_user, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/accounts/{account_id}/switch", response_model=MT5AccountSwitchRead)
def switch_saved_mt5_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MT5AccountSwitchRead:
    service = SavedMT5AccountService(db)
    row = service.get_for_user(current_user, account_id)
    try:
        result = MT5BridgeClient(timeout=130.0).switch_account(row.login, row.server)
    except MT5BridgeClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se pudo cambiar la cuenta en MT5: {exc}",
        ) from exc

    raw_account = result.get("account") if isinstance(result, dict) else None
    if not isinstance(raw_account, dict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El bridge no confirmó la nueva cuenta MT5")
    account = MT5AccountPayload.model_validate(raw_account)
    if account.login != row.login or (account.server or "").strip().casefold() != row.server.strip().casefold():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MT5 devolvió una cuenta distinta a la solicitada")

    service.mark_connected(row, account)
    previous = mt5_status_store.get()
    status_payload = MT5StatusPayload(
        connected_to_mt5=True,
        connected_to_backend=previous.connected_to_backend,
        account_trade_mode=account.trade_mode,
        account=account,
        terminal_trade_allowed=previous.terminal_trade_allowed,
        terminal_tradeapi_disabled=previous.terminal_tradeapi_disabled,
        active_symbols=previous.active_symbols,
        last_tick_time_by_symbol={},
        ticks_sent_total=previous.ticks_sent_total,
        last_batch_sent_at=None,
        errors_count=previous.errors_count,
        message=f"Cuenta MT5 cambiada a {account.login} · {account.server or ''}",
    )
    status_read = mt5_status_store.update(status_payload)
    snapshot_service = RiskSnapshotService(db)
    for symbol in ("XAUUSD", "XAUEUR"):
        snapshot_service.mark_dirty(symbol)
    db.commit()
    return MT5AccountSwitchRead(
        account=service.to_read(row, account),
        mt5_status=status_read,
        message="Cuenta MT5 cambiada correctamente",
    )


@router.post("/status", response_model=MT5StatusRead, dependencies=[Depends(require_service_token)])
def post_mt5_status(payload: MT5StatusPayload, db: Session = Depends(get_db)) -> MT5StatusRead:
    previous = mt5_status_store.get()
    status = mt5_status_store.update(payload)
    if _risk_account_changed(previous.account, payload.account):
        snapshot_service = RiskSnapshotService(db)
        for symbol in ("XAUUSD", "XAUEUR"):
            try:
                snapshot_service.mark_dirty(symbol)
            except Exception:  # noqa: BLE001
                logger.exception("risk_snapshot_mark_dirty_failed symbol=%s", symbol)
        db.commit()
    return status


def _risk_account_changed(previous, current) -> bool:
    if previous is None or current is None:
        return previous is not current
    return (
        previous.login != current.login
        or (previous.server or "") != (current.server or "")
        or (previous.currency or "") != (current.currency or "")
        or _rounded_money(previous.balance) != _rounded_money(current.balance)
    )


def _rounded_money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


@router.post("/positions/sync", response_model=MT5PositionsSyncRead, dependencies=[Depends(require_service_token)])
def sync_mt5_positions(
    payload: MT5PositionsSyncPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MT5PositionsSyncRead:
    result = PositionService(db).sync_mt5_positions(
        positions=payload.positions,
        account=payload.account,
        closed_deals=payload.closed_deals,
        deals_checked=payload.deals_checked,
    )
    imported_capital_flows = PerformanceService(db).sync_mt5_capital_flows(payload.capital_flows, payload.account)
    result["capital_flows_received"] = len(payload.capital_flows)
    result["capital_flows_created"] = imported_capital_flows
    for position in result.get("changed_positions", []):
        event_type = "position_closed" if position.get("status") == "CLOSED" else "position_updated"
        background_tasks.add_task(
            market_ws_manager.broadcast_position_event,
            {
                "type": event_type,
                "position_id": position.get("id"),
                "symbol": position.get("internal_symbol"),
                "source": "mt5_sync",
                "position": position,
            },
        )
    return MT5PositionsSyncRead(ok=True, **result)

from fastapi import APIRouter, BackgroundTasks, Depends
import logging
from sqlalchemy.orm import Session

from app.core.service_auth import require_service_token
from app.db.session import get_db
from app.mt5.schemas import MT5PositionsSyncPayload, MT5PositionsSyncRead, MT5StatusPayload, MT5StatusRead
from app.mt5.status_store import mt5_status_store
from app.positions.service import PositionService
from app.risk.snapshot import RiskSnapshotService
from app.websockets.manager import market_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mt5", tags=["mt5"])


@router.get("/status", response_model=MT5StatusRead)
def get_mt5_status() -> MT5StatusRead:
    return mt5_status_store.get()


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
    )
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

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.mt5.schemas import MT5PositionsSyncPayload, MT5PositionsSyncRead, MT5StatusPayload, MT5StatusRead
from app.mt5.status_store import mt5_status_store
from app.positions.service import PositionService
from app.websockets.manager import market_ws_manager

router = APIRouter(prefix="/mt5", tags=["mt5"])


@router.get("/status", response_model=MT5StatusRead)
def get_mt5_status() -> MT5StatusRead:
    return mt5_status_store.get()


@router.post("/status", response_model=MT5StatusRead)
def post_mt5_status(payload: MT5StatusPayload) -> MT5StatusRead:
    return mt5_status_store.update(payload)


@router.post("/positions/sync", response_model=MT5PositionsSyncRead)
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
    if result["created"] or result["updated"] or result["closed"]:
        background_tasks.add_task(
            market_ws_manager.broadcast_position_event,
            {
                "type": "position_closed" if result["closed"] else "position_updated",
                "position_id": 0,
                "symbol": "*",
                "source": "mt5_sync",
            },
        )
    return MT5PositionsSyncRead(ok=True, **result)

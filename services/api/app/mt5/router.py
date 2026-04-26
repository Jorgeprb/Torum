from fastapi import APIRouter

from app.mt5.schemas import MT5StatusPayload, MT5StatusRead
from app.mt5.status_store import mt5_status_store

router = APIRouter(prefix="/mt5", tags=["mt5"])


@router.get("/status", response_model=MT5StatusRead)
def get_mt5_status() -> MT5StatusRead:
    return mt5_status_store.get()


@router.post("/status", response_model=MT5StatusRead)
def post_mt5_status(payload: MT5StatusPayload) -> MT5StatusRead:
    return mt5_status_store.update(payload)

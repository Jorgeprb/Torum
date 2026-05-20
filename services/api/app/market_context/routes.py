from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_context.dollar_strength import DollarStrengthService
from app.market_context.schemas import DollarStrengthRead, DollarStrengthRecomputeRead

router = APIRouter(prefix="/market-context", tags=["market-context"])


@router.get("/dollar-strength", response_model=DollarStrengthRead)
def get_dollar_strength(db: Session = Depends(get_db)) -> DollarStrengthRead:
    return DollarStrengthService(db).latest_snapshot_read()


@router.post("/dollar-strength/recompute", response_model=DollarStrengthRecomputeRead)
def recompute_dollar_strength(db: Session = Depends(get_db)) -> DollarStrengthRecomputeRead:
    snapshot = DollarStrengthService(db).recompute()
    return DollarStrengthRecomputeRead(ok=True, snapshot=snapshot, message="dxy_recomputed")

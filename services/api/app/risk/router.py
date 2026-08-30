from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.risk.schemas import RiskCandidatePreviewRead, RiskSnapshotRead, StopOutLineRead
from app.risk.snapshot import RiskSnapshotService
from app.risk.stopout import StopOutLineService
from app.users.models import User

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/snapshot", response_model=RiskSnapshotRead)
def get_risk_snapshot(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(..., min_length=3, max_length=32),
    source: str = Query("ALL", min_length=2, max_length=16),
) -> RiskSnapshotRead:
    return RiskSnapshotService(db).get_snapshot(symbol, source=source).to_read()


@router.post("/recompute", response_model=RiskSnapshotRead)
def recompute_risk_snapshot(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(..., min_length=3, max_length=32),
    source: str = Query("ALL", min_length=2, max_length=16),
) -> RiskSnapshotRead:
    return RiskSnapshotService(db).recompute(symbol, source=source).to_read()


@router.get("/candidate-preview", response_model=RiskCandidatePreviewRead)
def get_risk_candidate_preview(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(..., min_length=3, max_length=32),
    side: str = Query("BUY", min_length=3, max_length=4),
    volume: float = Query(..., gt=0),
    price: float | None = Query(default=None, gt=0),
    source: str = Query("ALL", min_length=2, max_length=16),
) -> RiskCandidatePreviewRead:
    return RiskSnapshotService(db).preview_candidate(symbol, side=side, volume=volume, price=price, source=source)


@router.get("/stopout-line", response_model=StopOutLineRead)
def get_stopout_line(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(..., min_length=3, max_length=32),
) -> StopOutLineRead:
    return StopOutLineService(db).get_line(symbol)

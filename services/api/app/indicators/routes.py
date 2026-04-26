from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.indicators.engine import IndicatorEngine
from app.indicators.repository import (
    get_indicator_config,
    list_indicator_configs,
    list_indicators,
)
from app.indicators.schemas import (
    IndicatorCalculationResponse,
    IndicatorConfigCreate,
    IndicatorConfigRead,
    IndicatorConfigUpdate,
    IndicatorRead,
)
from app.indicators.service import IndicatorService
from app.market_data.timeframes import Timeframe
from app.users.models import User

router = APIRouter(tags=["indicators"])


@router.get("/indicators", response_model=list[IndicatorRead])
def get_indicators(db: Annotated[Session, Depends(get_db)]) -> list[IndicatorRead]:
    return [IndicatorRead.model_validate(indicator) for indicator in list_indicators(db)]


@router.post("/indicators/register-defaults", response_model=list[IndicatorRead])
def register_defaults(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[IndicatorRead]:
    return [IndicatorRead.model_validate(indicator) for indicator in IndicatorService(db).register_defaults()]


@router.get("/indicator-configs", response_model=list[IndicatorConfigRead])
def get_indicator_configs(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None, min_length=3),
    timeframe: Timeframe | None = None,
) -> list[IndicatorConfigRead]:
    return [
        IndicatorConfigRead.model_validate(config)
        for config in list_indicator_configs(db, symbol=symbol, timeframe=timeframe)
    ]


@router.post("/indicator-configs", response_model=IndicatorConfigRead, status_code=status.HTTP_201_CREATED)
def create_indicator_config(
    payload: IndicatorConfigCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> IndicatorConfigRead:
    return IndicatorConfigRead.model_validate(IndicatorService(db).create_config(payload, user_id=current_user.id))


@router.patch("/indicator-configs/{config_id}", response_model=IndicatorConfigRead)
def update_indicator_config(
    config_id: int,
    payload: IndicatorConfigUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> IndicatorConfigRead:
    config = get_indicator_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indicator config not found")
    return IndicatorConfigRead.model_validate(IndicatorService(db).update_config(config, payload))


@router.delete("/indicator-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_indicator_config(
    config_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    config = get_indicator_config(db, config_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indicator config not found")
    IndicatorService(db).delete_config(config)


@router.get("/indicators/calculate", response_model=IndicatorCalculationResponse)
def calculate_indicator(
    db: Annotated[Session, Depends(get_db)],
    symbol: str = Query(min_length=3),
    timeframe: Timeframe = Query(),
    indicator: str = Query(min_length=2),
    period: int | None = Query(default=None, ge=1, le=1000),
    limit: int = Query(default=300, ge=1, le=5000),
) -> IndicatorCalculationResponse:
    params: dict[str, object] = {}
    if period is not None:
        params["period"] = period
    return IndicatorCalculationResponse.model_validate(
        IndicatorEngine(db).calculate(
            plugin_key=indicator,
            symbol=symbol,
            timeframe=timeframe,
            params=params,
            limit=limit,
        )
    )

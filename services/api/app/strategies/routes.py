from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.strategies.repository import get_config, get_signal, list_configs, list_definitions, list_runs, list_signals
from app.strategies.runner import StrategyRunner
from app.strategies.schemas import (
    StrategyConfigCreate,
    StrategyConfigRead,
    StrategyConfigUpdate,
    StrategyDefinitionRead,
    StrategyRunRead,
    StrategyRunResult,
    StrategySettingsRead,
    StrategySettingsUpdate,
    StrategySignalRead,
)
from app.strategies.service import StrategyCatalogService
from app.users.models import User

router = APIRouter(tags=["strategies"])


@router.get("/strategies", response_model=list[StrategyDefinitionRead])
def get_strategies(db: Annotated[Session, Depends(get_db)]) -> list[StrategyDefinitionRead]:
    return [StrategyDefinitionRead.model_validate(definition) for definition in list_definitions(db)]


@router.post("/strategies/register-defaults", response_model=list[StrategyDefinitionRead])
def register_strategy_defaults(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[StrategyDefinitionRead]:
    return [StrategyDefinitionRead.model_validate(item) for item in StrategyCatalogService(db).register_defaults()]


@router.get("/strategy-configs", response_model=list[StrategyConfigRead])
def get_strategy_configs(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[StrategyConfigRead]:
    return [StrategyConfigRead.model_validate(config) for config in list_configs(db, user_id=current_user.id)]


@router.post("/strategy-configs", response_model=StrategyConfigRead, status_code=status.HTTP_201_CREATED)
def create_strategy_config(
    payload: StrategyConfigCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyConfigRead:
    return StrategyConfigRead.model_validate(StrategyCatalogService(db).create_config(payload, current_user.id))


@router.patch("/strategy-configs/{config_id}", response_model=StrategyConfigRead)
def update_strategy_config(
    config_id: int,
    payload: StrategyConfigUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyConfigRead:
    config = get_config(db, config_id)
    if config is None or config.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy config not found")
    return StrategyConfigRead.model_validate(StrategyCatalogService(db).update_config(config, payload))


@router.delete("/strategy-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_strategy_config(
    config_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    config = get_config(db, config_id)
    if config is None or config.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy config not found")
    StrategyCatalogService(db).delete_config(config)


@router.get("/strategy-settings", response_model=StrategySettingsRead)
def get_strategy_settings(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> StrategySettingsRead:
    return StrategySettingsRead.model_validate(StrategyCatalogService(db).settings())


@router.patch("/strategy-settings", response_model=StrategySettingsRead)
def update_strategy_settings(
    payload: StrategySettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> StrategySettingsRead:
    return StrategySettingsRead.model_validate(StrategyCatalogService(db).update_settings(payload))


@router.post("/strategies/run", response_model=list[StrategyRunResult])
def run_all_enabled_strategies(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[StrategyRunResult]:
    return [StrategyRunner(db).run_config(config, current_user) for config in list_configs(db, user_id=current_user.id) if config.enabled]


@router.post("/strategies/run/{config_id}", response_model=StrategyRunResult)
def run_strategy_config(
    config_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyRunResult:
    config = get_config(db, config_id)
    if config is None or config.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy config not found")
    return StrategyRunner(db).run_config(config, current_user)


@router.get("/strategy-signals", response_model=list[StrategySignalRead])
def get_strategy_signals(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StrategySignalRead]:
    return [StrategySignalRead.model_validate(signal) for signal in list_signals(db, limit=limit)]


@router.get("/strategy-signals/{signal_id}", response_model=StrategySignalRead)
def get_strategy_signal(
    signal_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> StrategySignalRead:
    signal = get_signal(db, signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy signal not found")
    return StrategySignalRead.model_validate(signal)


@router.get("/strategy-runs", response_model=list[StrategyRunRead])
def get_strategy_runs(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StrategyRunRead]:
    return [StrategyRunRead.model_validate(run) for run in list_runs(db, limit=limit)]

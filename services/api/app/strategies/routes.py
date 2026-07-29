from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.strategies.repository import get_config, get_config_version, get_signal, list_config_versions, list_configs, list_definitions, list_runs, list_signals
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
    StrategyConfigVersionRead,
    TorumV1ConfigurationRead,
    TorumV1ConfigurationUpdate,
    TorumV1ReplayRead,
    TorumV1ReplayRequest,
    TorumV1BacktestRead,
    TorumV1BacktestRequest,
    TorumV1BacktestJobRead,
    TorumV1SimulationRead,
    TorumV1SimulationRequest,
    TorumV1StatusRead,
)
from app.strategies.service import StrategyCatalogService
from app.strategies.torum_v1 import TorumV1StatusService
from app.strategies.torum_v1_config import TORUM_SYMBOLS, TorumV1Params, ui_schema
from app.strategies.torum_v1_simulator import TorumV1Simulator
from app.strategies.torum_v1_backtest import TorumV1BacktestEngine
from app.strategies.torum_v1_backtest_jobs import backtest_job_manager
from app.strategies.pullback_cache import get_cached_pullbacks, invalidate_pullback_cache
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


@router.get("/strategies/torum-v1/status", response_model=TorumV1StatusRead)
def get_torum_v1_status(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1StatusRead:
    status_payload = asdict(TorumV1StatusService(db).status_for_user(current_user.id))
    return TorumV1StatusRead.model_validate(status_payload)


@router.get("/strategies/torum-v1/configuration/schema")
def get_torum_v1_configuration_schema(
    _current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    return ui_schema()


@router.get("/strategies/torum-v1/configuration", response_model=TorumV1ConfigurationRead)
def get_torum_v1_configuration(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1ConfigurationRead:
    rows = {
        config.internal_symbol.upper(): config
        for config in list_configs(db, user_id=current_user.id)
        if config.strategy_key == "torum_v1" and config.internal_symbol.upper() in TORUM_SYMBOLS
    }
    normalized = {
        symbol: TorumV1Params.normalize(symbol, rows[symbol].params_json if symbol in rows else None).model_dump()
        for symbol in TORUM_SYMBOLS
    }
    base = dict(normalized[TORUM_SYMBOLS[0]])
    for key in list(base):
        if any(normalized[symbol].get(key) != base[key] for symbol in TORUM_SYMBOLS[1:]):
            base.pop(key, None)
    overrides = {
        symbol: {key: value for key, value in params.items() if key not in base or base.get(key) != value}
        for symbol, params in normalized.items()
    }
    configs = {symbol: StrategyConfigRead.model_validate(config) for symbol, config in rows.items()}
    return TorumV1ConfigurationRead(
        base_params=base,
        asset_overrides=overrides,
        configs=configs,
        enabled_by_symbol={symbol: bool(rows[symbol].enabled) if symbol in rows else True for symbol in TORUM_SYMBOLS},
        mode_by_symbol={symbol: rows[symbol].mode if symbol in rows else "PAPER" for symbol in TORUM_SYMBOLS},
        schema=ui_schema(),
        common_revision=max((int(item.revision or 1) for item in rows.values()), default=0),
    )


@router.patch("/strategies/torum-v1/configuration", response_model=TorumV1ConfigurationRead)
def patch_torum_v1_configuration(
    payload: TorumV1ConfigurationUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1ConfigurationRead:
    try:
        updated = StrategyCatalogService(db).update_torum_bundle(
            user_id=current_user.id,
            base_params=payload.base_params,
            asset_overrides=payload.asset_overrides,
            enabled_by_symbol=payload.enabled_by_symbol,
            mode_by_symbol=payload.mode_by_symbol,
            expected_revisions=payload.expected_revisions,
            change_note=payload.change_note,
        )
    except ValueError as exc:
        if str(exc).startswith("strategy_config_revision_conflict"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    for item in updated:
        invalidate_pullback_cache(user_id=current_user.id, symbol=item.internal_symbol)
    return get_torum_v1_configuration(db, current_user)


@router.post("/strategies/torum-v1/simulate", response_model=TorumV1SimulationRead)
def simulate_torum_v1(
    payload: TorumV1SimulationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1SimulationRead:
    config = next(
        (
            item
            for item in list_configs(db, user_id=current_user.id)
            if item.strategy_key == "torum_v1" and item.internal_symbol.upper() == payload.symbol
        ),
        None,
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Torum V1 config not found")
    try:
        return TorumV1Simulator(db).simulate(config, params_override=payload.params, candle_limit=payload.candle_limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/strategies/torum-v1/backtest/jobs",
    response_model=TorumV1BacktestJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_torum_v1_backtest_job(
    payload: TorumV1BacktestRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1BacktestJobRead:
    config = next(
        (
            item
            for item in list_configs(db, user_id=current_user.id)
            if item.strategy_key == "torum_v1" and item.internal_symbol.upper() == payload.symbol
        ),
        None,
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Torum V1 config not found")
    return TorumV1BacktestJobRead.model_validate(
        backtest_job_manager.start(
            user_id=current_user.id,
            config_id=config.id,
            request=payload,
        )
    )


@router.get(
    "/strategies/torum-v1/backtest/jobs/{job_id}",
    response_model=TorumV1BacktestJobRead,
)
def get_torum_v1_backtest_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    include_result: bool = Query(default=True),
) -> TorumV1BacktestJobRead:
    job = backtest_job_manager.get(
        job_id=job_id,
        user_id=current_user.id,
        include_result=include_result,
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest job not found")
    return TorumV1BacktestJobRead.model_validate(job)


@router.delete(
    "/strategies/torum-v1/backtest/jobs/{job_id}",
    response_model=TorumV1BacktestJobRead,
)
def cancel_torum_v1_backtest_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1BacktestJobRead:
    job = backtest_job_manager.cancel(job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest job not found")
    return TorumV1BacktestJobRead.model_validate(job)


@router.post("/strategies/torum-v1/backtest", response_model=TorumV1BacktestRead)
def backtest_torum_v1(
    payload: TorumV1BacktestRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1BacktestRead:
    config = next(
        (
            item
            for item in list_configs(db, user_id=current_user.id)
            if item.strategy_key == "torum_v1" and item.internal_symbol.upper() == payload.symbol
        ),
        None,
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Torum V1 config not found")
    try:
        return TorumV1BacktestEngine(db).run(config, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/strategies/torum-v1/simulate/history", response_model=TorumV1ReplayRead)
def replay_torum_v1(
    payload: TorumV1ReplayRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TorumV1ReplayRead:
    config = next(
        (
            item
            for item in list_configs(db, user_id=current_user.id)
            if item.strategy_key == "torum_v1" and item.internal_symbol.upper() == payload.symbol
        ),
        None,
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Torum V1 config not found")
    try:
        return TorumV1Simulator(db).replay(
            config,
            params_override=payload.params,
            candle_limit=payload.candle_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/strategy-configs/{config_id}/versions", response_model=list[StrategyConfigVersionRead])
def get_strategy_config_versions(
    config_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[StrategyConfigVersionRead]:
    config = get_config(db, config_id)
    if config is None or config.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy config not found")
    return [StrategyConfigVersionRead.model_validate(item) for item in list_config_versions(db, config_id, limit)]


@router.post("/strategy-configs/{config_id}/versions/{revision}/restore", response_model=StrategyConfigRead)
def restore_strategy_config_version(
    config_id: int,
    revision: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyConfigRead:
    config = get_config(db, config_id)
    version = get_config_version(db, config_id, revision)
    if config is None or config.user_id != current_user.id or version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy config version not found")
    restored = StrategyCatalogService(db).restore_version(config, version, user_id=current_user.id)
    invalidate_pullback_cache(user_id=current_user.id, symbol=config.internal_symbol)
    return StrategyConfigRead.model_validate(restored)


@router.get("/strategies/torum-v1/pullbacks")
def get_torum_v1_pullbacks(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(min_length=3, max_length=32),
    force: bool = Query(default=False),
    limit: int = Query(default=600, ge=100, le=2000),
) -> dict[str, object]:
    payload, cache_hit, calculated_at = get_cached_pullbacks(
        db, user_id=current_user.id, symbol=symbol, force=force, candle_limit=limit
    )
    return {
        "symbol": symbol.upper(),
        "timeframe": "M5",
        "pullbacks": payload,
        "cache_hit": cache_hit,
        "calculated_at": calculated_at.isoformat() if calculated_at else None,
    }


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
    try:
        updated = StrategyCatalogService(db).update_config(config, payload, user_id=current_user.id)
    except ValueError as exc:
        if str(exc).startswith("strategy_config_revision_conflict"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    invalidate_pullback_cache(user_id=current_user.id, symbol=config.internal_symbol)
    return StrategyConfigRead.model_validate(updated)


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
    invalidate_pullback_cache(user_id=current_user.id, symbol=config.internal_symbol)


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
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StrategySignalRead]:
    return [StrategySignalRead.model_validate(signal) for signal in list_signals(db, limit=limit, user_id=current_user.id)]


@router.get("/strategy-signals/{signal_id}", response_model=StrategySignalRead)
def get_strategy_signal(
    signal_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategySignalRead:
    signal = get_signal(db, signal_id, user_id=current_user.id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy signal not found")
    return StrategySignalRead.model_validate(signal)


@router.get("/strategy-runs", response_model=list[StrategyRunRead])
def get_strategy_runs(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StrategyRunRead]:
    return [StrategyRunRead.model_validate(run) for run in list_runs(db, limit=limit, user_id=current_user.id)]

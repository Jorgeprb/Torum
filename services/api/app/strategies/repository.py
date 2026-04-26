from sqlalchemy import select
from sqlalchemy.orm import Session

from app.strategies.models import StrategyConfig, StrategyDefinition, StrategyRun, StrategySettings, StrategySignal


def list_definitions(db: Session) -> list[StrategyDefinition]:
    return list(db.scalars(select(StrategyDefinition).order_by(StrategyDefinition.key)))


def get_definition(db: Session, key: str) -> StrategyDefinition | None:
    return db.scalar(select(StrategyDefinition).where(StrategyDefinition.key == key.lower()))


def get_config(db: Session, config_id: int) -> StrategyConfig | None:
    return db.get(StrategyConfig, config_id)


def list_configs(db: Session, *, user_id: int | None = None) -> list[StrategyConfig]:
    stmt = select(StrategyConfig)
    if user_id is not None:
        stmt = stmt.where(StrategyConfig.user_id == user_id)
    return list(db.scalars(stmt.order_by(StrategyConfig.id)))


def get_global_strategy_settings(db: Session) -> StrategySettings:
    settings = db.scalar(select(StrategySettings).where(StrategySettings.user_id.is_(None)))
    if settings is not None:
        return settings
    settings = StrategySettings(
        user_id=None,
        strategies_enabled=False,
        strategy_live_enabled=False,
        default_mode="PAPER",
        max_signals_per_run=10,
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def list_signals(db: Session, limit: int = 100) -> list[StrategySignal]:
    return list(db.scalars(select(StrategySignal).order_by(StrategySignal.created_at.desc(), StrategySignal.id.desc()).limit(limit)))


def get_signal(db: Session, signal_id: int) -> StrategySignal | None:
    return db.get(StrategySignal, signal_id)


def list_runs(db: Session, limit: int = 100) -> list[StrategyRun]:
    return list(db.scalars(select(StrategyRun).order_by(StrategyRun.started_at.desc(), StrategyRun.id.desc()).limit(limit)))

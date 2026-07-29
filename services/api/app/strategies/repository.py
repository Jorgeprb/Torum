from sqlalchemy import select
from sqlalchemy.orm import Session

from app.strategies.models import StrategyConfig, StrategyConfigVersion, StrategyDefinition, StrategyRun, StrategySettings, StrategySignal


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


def list_signals(db: Session, limit: int = 100, *, user_id: int | None = None) -> list[StrategySignal]:
    stmt = select(StrategySignal)
    if user_id is not None:
        stmt = stmt.where(StrategySignal.user_id == user_id)
    return list(db.scalars(stmt.order_by(StrategySignal.created_at.desc(), StrategySignal.id.desc()).limit(limit)))


def get_signal(db: Session, signal_id: int, *, user_id: int | None = None) -> StrategySignal | None:
    stmt = select(StrategySignal).where(StrategySignal.id == signal_id)
    if user_id is not None:
        stmt = stmt.where(StrategySignal.user_id == user_id)
    return db.scalar(stmt)


def list_runs(db: Session, limit: int = 100, *, user_id: int | None = None) -> list[StrategyRun]:
    stmt = select(StrategyRun)
    if user_id is not None:
        stmt = stmt.join(StrategyConfig, StrategyRun.strategy_config_id == StrategyConfig.id).where(StrategyConfig.user_id == user_id)
    return list(db.scalars(stmt.order_by(StrategyRun.started_at.desc(), StrategyRun.id.desc()).limit(limit)))


def list_config_versions(db: Session, config_id: int, limit: int = 50) -> list[StrategyConfigVersion]:
    return list(
        db.scalars(
            select(StrategyConfigVersion)
            .where(StrategyConfigVersion.strategy_config_id == config_id)
            .order_by(StrategyConfigVersion.revision.desc())
            .limit(limit)
        )
    )


def get_config_version(db: Session, config_id: int, revision: int) -> StrategyConfigVersion | None:
    return db.scalar(
        select(StrategyConfigVersion).where(
            StrategyConfigVersion.strategy_config_id == config_id,
            StrategyConfigVersion.revision == revision,
        )
    )

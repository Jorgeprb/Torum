from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indicators.models import Indicator, IndicatorConfig


def list_indicators(db: Session) -> list[Indicator]:
    return list(db.scalars(select(Indicator).order_by(Indicator.name)))


def get_indicator(db: Session, indicator_id: int) -> Indicator | None:
    return db.get(Indicator, indicator_id)


def get_indicator_by_plugin_key(db: Session, plugin_key: str) -> Indicator | None:
    return db.scalar(select(Indicator).where(Indicator.plugin_key == plugin_key.upper()))


def list_indicator_configs(
    db: Session,
    symbol: str | None = None,
    timeframe: str | None = None,
    enabled_only: bool = False,
) -> list[IndicatorConfig]:
    stmt = select(IndicatorConfig)
    if symbol:
        stmt = stmt.where(IndicatorConfig.internal_symbol == symbol.upper())
    if timeframe:
        stmt = stmt.where(IndicatorConfig.timeframe == timeframe)
    if enabled_only:
        stmt = stmt.where(IndicatorConfig.enabled.is_(True))
    return list(db.scalars(stmt.order_by(IndicatorConfig.id)))


def get_indicator_config(db: Session, config_id: int) -> IndicatorConfig | None:
    return db.get(IndicatorConfig, config_id)

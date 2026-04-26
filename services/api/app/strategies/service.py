from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.strategies.models import StrategyConfig, StrategyDefinition, StrategySettings
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_definition, get_global_strategy_settings
from app.strategies.schemas import StrategyConfigCreate, StrategyConfigUpdate, StrategySettingsUpdate


class StrategyCatalogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register_defaults(self) -> list[StrategyDefinition]:
        registered: list[StrategyDefinition] = []
        for plugin in strategy_registry.list():
            definition = get_definition(self.db, plugin.key)
            if definition is None:
                definition = StrategyDefinition(
                    key=plugin.key,
                    name=plugin.name,
                    version=plugin.version,
                    description=plugin.description,
                    enabled=True,
                    default_params_json=plugin.default_params,
                )
                self.db.add(definition)
            else:
                definition.name = plugin.name
                definition.version = plugin.version
                definition.description = plugin.description
                definition.default_params_json = plugin.default_params
            registered.append(definition)
        self.db.commit()
        for definition in registered:
            self.db.refresh(definition)
        return registered

    def create_config(self, payload: StrategyConfigCreate, user_id: int | None) -> StrategyConfig:
        config = StrategyConfig(user_id=user_id, **payload.model_dump())
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(self, config: StrategyConfig, payload: StrategyConfigUpdate) -> StrategyConfig:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(config, field, value)
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_config(self, config: StrategyConfig) -> None:
        self.db.delete(config)
        self.db.commit()

    def settings(self) -> StrategySettings:
        return get_global_strategy_settings(self.db)

    def update_settings(self, payload: StrategySettingsUpdate) -> StrategySettings:
        settings = get_global_strategy_settings(self.db)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(settings, field, value)
        self.db.commit()
        self.db.refresh(settings)
        return settings


def seed_strategy_engine_defaults() -> None:
    with SessionLocal() as db:
        StrategyCatalogService(db).register_defaults()
        get_global_strategy_settings(db)

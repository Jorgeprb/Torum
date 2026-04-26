from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indicators.engine import IndicatorEngine
from app.indicators.models import Indicator, IndicatorConfig
from app.indicators.registry import indicator_registry
from app.indicators.repository import get_indicator, get_indicator_by_plugin_key, list_indicator_configs
from app.indicators.schemas import IndicatorConfigCreate, IndicatorConfigUpdate


class IndicatorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register_defaults(self) -> list[Indicator]:
        registered: list[Indicator] = []
        for plugin in indicator_registry.list():
            indicator = get_indicator_by_plugin_key(self.db, plugin.key)
            if indicator is None:
                indicator = Indicator(
                    name=plugin.name,
                    plugin_key=plugin.key,
                    version=plugin.version,
                    description=plugin.description,
                    output_type=plugin.supported_outputs[0],
                    enabled=plugin.key != "CUSTOM_ZONE_EXAMPLE",
                    default_params_json=plugin.default_params,
                )
                self.db.add(indicator)
            else:
                indicator.name = plugin.name
                indicator.version = plugin.version
                indicator.description = plugin.description
                indicator.output_type = plugin.supported_outputs[0]
                indicator.default_params_json = plugin.default_params
            registered.append(indicator)
        self.db.commit()
        for indicator in registered:
            self.db.refresh(indicator)
        self._seed_dxy_sma30()
        return registered

    def create_config(self, payload: IndicatorConfigCreate, user_id: int | None = None) -> IndicatorConfig:
        config = IndicatorConfig(user_id=user_id, **payload.model_dump())
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(self, config: IndicatorConfig, payload: IndicatorConfigUpdate) -> IndicatorConfig:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(config, field, value)
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_config(self, config: IndicatorConfig) -> None:
        self.db.delete(config)
        self.db.commit()

    def calculate_active_overlays(self, symbol: str, timeframe: str) -> list[dict[str, object]]:
        overlays: list[dict[str, object]] = []
        configs = list_indicator_configs(self.db, symbol=symbol, timeframe=timeframe, enabled_only=True)
        engine = IndicatorEngine(self.db)
        for config in configs:
            indicator = get_indicator(self.db, config.indicator_id)
            if indicator is None or not indicator.enabled:
                continue
            overlays.append(engine.calculate_config(config, plugin_key=indicator.plugin_key)["output"])
        return overlays

    def _seed_dxy_sma30(self) -> None:
        indicator = get_indicator_by_plugin_key(self.db, "SMA")
        if indicator is None:
            return
        existing = self.db.scalar(
            select(IndicatorConfig).where(
                IndicatorConfig.user_id.is_(None),
                IndicatorConfig.indicator_id == indicator.id,
                IndicatorConfig.internal_symbol == "DXY",
                IndicatorConfig.timeframe == "D1",
            )
        )
        if existing is not None:
            return
        self.db.add(
            IndicatorConfig(
                user_id=None,
                indicator_id=indicator.id,
                internal_symbol="DXY",
                timeframe="D1",
                enabled=True,
                params_json={"period": 30},
                display_settings_json={"color": "#d6b25e", "lineWidth": 2},
            )
        )
        self.db.commit()


def seed_default_indicators() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        IndicatorService(db).register_defaults()

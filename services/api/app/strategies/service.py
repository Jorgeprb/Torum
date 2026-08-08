from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.strategies.models import StrategyConfig, StrategyConfigVersion, StrategyDefinition, StrategySettings
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_definition, get_global_strategy_settings
from app.strategies.schemas import StrategyConfigCreate, StrategyConfigUpdate, StrategySettingsUpdate
from app.strategies.torum_v1_config import TORUM_SYMBOLS, TorumV1Params


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
        data = payload.model_dump()
        if payload.strategy_key == "torum_v1":
            data["params_json"] = TorumV1Params.normalize(payload.internal_symbol, payload.params_json).model_dump()
            if bool(payload.enabled):
                self._deactivate_other_torum_configs(
                    user_id=user_id,
                    symbol=payload.internal_symbol,
                    exclude_id=None,
                )
        config = StrategyConfig(user_id=user_id, revision=1, **data)
        self.db.add(config)
        self.db.flush()
        self._snapshot_version(config, user_id=user_id, change_note="Configuración inicial")
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(self, config: StrategyConfig, payload: StrategyConfigUpdate, *, user_id: int | None = None) -> StrategyConfig:
        data = payload.model_dump(exclude_unset=True)
        expected_revision = data.pop("expected_revision", None)
        change_note = data.pop("change_note", None)
        # Optional API fields may be sent explicitly as null. They mean "leave
        # unchanged" for execution-critical scalar settings; persisting NULL
        # would violate the DB contract and could disable the runner entirely.
        for field in ("enabled", "mode", "params_json"):
            if data.get(field) is None:
                data.pop(field, None)
        if expected_revision is not None and int(config.revision or 1) != expected_revision:
            raise ValueError(f"strategy_config_revision_conflict:{config.revision}")
        target_enabled = bool(data.get("enabled", config.enabled))
        if config.strategy_key == "torum_v1" and target_enabled:
            self._deactivate_other_torum_configs(
                user_id=config.user_id,
                symbol=config.internal_symbol,
                exclude_id=config.id,
            )
        if config.strategy_key == "torum_v1" and "params_json" in data:
            data["params_json"] = TorumV1Params.normalize(config.internal_symbol, data["params_json"]).model_dump()
        for field, value in data.items():
            setattr(config, field, value)
        config.revision = int(config.revision or 1) + 1
        self.db.flush()
        self._snapshot_version(config, user_id=user_id, change_note=change_note)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_torum_bundle(
        self,
        *,
        user_id: int,
        base_params: dict,
        asset_overrides: dict[str, dict],
        enabled_by_symbol: dict[str, bool],
        mode_by_symbol: dict[str, str],
        expected_revisions: dict[str, int],
        change_note: str | None,
    ) -> list[StrategyConfig]:
        from app.strategies.repository import list_configs

        candidates = sorted(
            (
                item
                for item in list_configs(self.db, user_id=user_id)
                if item.strategy_key == "torum_v1" and item.internal_symbol.upper() in TORUM_SYMBOLS
            ),
            key=lambda item: (int(item.revision or 1), int(item.id or 0)),
        )
        existing = {item.internal_symbol.upper(): item for item in candidates}
        updated: list[StrategyConfig] = []
        try:
            for symbol in TORUM_SYMBOLS:
                config = existing.get(symbol)
                merged = {**base_params, **asset_overrides.get(symbol, {})}
                normalized = TorumV1Params.normalize(symbol, merged).model_dump()
                target_enabled = enabled_by_symbol.get(
                    symbol,
                    config.enabled if config is not None else bool(normalized.get("enabled", True)),
                )
                if target_enabled:
                    self._deactivate_other_torum_configs(
                        user_id=user_id,
                        symbol=symbol,
                        exclude_id=config.id if config is not None else None,
                    )
                if config is None:
                    config = StrategyConfig(
                        user_id=user_id,
                        strategy_key="torum_v1",
                        internal_symbol=symbol,
                        timeframe=normalized["timeframe"],
                        enabled=target_enabled,
                        mode=mode_by_symbol.get(symbol, "PAPER"),
                        params_json=normalized,
                        revision=1,
                    )
                    self.db.add(config)
                    self.db.flush()
                else:
                    expected = expected_revisions.get(symbol)
                    if expected is not None and int(config.revision or 1) != int(expected):
                        raise ValueError(f"strategy_config_revision_conflict:{symbol}:{config.revision}")
                    config.params_json = normalized
                    config.timeframe = normalized["timeframe"]
                    config.enabled = target_enabled
                    config.mode = mode_by_symbol.get(symbol, config.mode)
                    config.revision = int(config.revision or 1) + 1
                self.db.flush()
                self._snapshot_version(config, user_id=user_id, change_note=change_note or "Actualización del editor Torum")
                updated.append(config)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for config in updated:
            self.db.refresh(config)
        return updated

    def restore_version(
        self, config: StrategyConfig, version: StrategyConfigVersion, *, user_id: int | None = None
    ) -> StrategyConfig:
        if config.strategy_key == "torum_v1" and version.enabled:
            self._deactivate_other_torum_configs(
                user_id=config.user_id,
                symbol=config.internal_symbol,
                exclude_id=config.id,
            )
        config.enabled = version.enabled
        config.mode = version.mode
        config.timeframe = version.timeframe
        config.params_json = TorumV1Params.normalize(config.internal_symbol, version.params_json).model_dump() if config.strategy_key == "torum_v1" else version.params_json
        config.risk_profile_json = version.risk_profile_json
        config.schedule_json = version.schedule_json
        config.revision = int(config.revision or 1) + 1
        self.db.flush()
        self._snapshot_version(config, user_id=user_id, change_note=f"Restaurada revisión {version.revision}")
        self.db.commit()
        self.db.refresh(config)
        return config

    def _snapshot_version(self, config: StrategyConfig, *, user_id: int | None, change_note: str | None) -> None:
        self.db.add(
            StrategyConfigVersion(
                strategy_config_id=config.id,
                user_id=user_id,
                revision=int(config.revision or 1),
                enabled=bool(config.enabled),
                mode=config.mode,
                timeframe=config.timeframe,
                params_json=dict(config.params_json or {}),
                risk_profile_json=dict(config.risk_profile_json) if config.risk_profile_json else None,
                schedule_json=dict(config.schedule_json) if config.schedule_json else None,
                change_note=change_note,
            )
        )

    def _deactivate_other_torum_configs(
        self,
        *,
        user_id: int | None,
        symbol: str,
        exclude_id: int | None,
    ) -> None:
        """Keep exactly one enabled Torum configuration per user and asset.

        Mode is a property of that active configuration, not a second execution
        lane.  Allowing DEMO and LIVE rows to remain enabled together caused the
        same candle to be evaluated twice with different revisions.
        """

        stmt = select(StrategyConfig).where(
            StrategyConfig.strategy_key == "torum_v1",
            StrategyConfig.user_id == user_id,
            StrategyConfig.internal_symbol == symbol.upper(),
            StrategyConfig.enabled.is_(True),
        )
        if exclude_id is not None:
            stmt = stmt.where(StrategyConfig.id != exclude_id)
        for other in self.db.scalars(stmt.with_for_update()):
            other.enabled = False
            other.revision = int(other.revision or 1) + 1
            self._snapshot_version(
                other,
                user_id=user_id,
                change_note="Desactivada automáticamente al activar otra configuración Torum del mismo activo",
            )

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

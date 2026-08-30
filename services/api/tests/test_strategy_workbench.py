from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Import domain models so SQLAlchemy registers all foreign-key targets.
from app.candles.models import Candle  # noqa: F401
from app.db.base import Base
from app.drawings.models import ChartDrawing  # noqa: F401
from app.market_context.models import DollarStrengthSnapshot  # noqa: F401
from app.news.models import NewsEvent, NewsSettings  # noqa: F401
from app.no_trade_zones.models import NoTradeZone  # noqa: F401
from app.orders.models import Order
from app.positions.models import Position  # noqa: F401
from app.risk.models import RiskSnapshotRecord  # noqa: F401
from app.settings.trading_settings import TradingSettings  # noqa: F401
from app.strategies.models import StrategyConfig, StrategyConfigVersion
from app.strategies.repository import list_configs, list_config_versions
from app.strategies.service import StrategyCatalogService
from app.strategies.routes import set_torum_v1_manual_lock_state
from app.strategies.schemas import TorumV1ManualLockStateUpdate
from app.strategies.torum_v1_config import TorumV1Params, ui_schema
from app.strategies.torum_v1_simulator import TorumV1Simulator
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.users.models import User, UserRole


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = testing_session()
    db.add(User(id=1, username="admin", email="admin@example.com", hashed_password="x", role=UserRole.admin, is_active=True))
    for symbol, tradable, analysis_only, contract_size in (
        ("XAUUSD", True, False, 100.0),
        ("XAUEUR", True, False, 100.0),
        ("DXY", False, True, 1.0),
    ):
        db.add(
            SymbolMapping(
                internal_symbol=symbol,
                broker_symbol=symbol,
                display_name=symbol,
                enabled=True,
                asset_class="METAL" if symbol != "DXY" else "INDEX",
                tradable=tradable,
                analysis_only=analysis_only,
                digits=2,
                point=0.01,
                contract_size=contract_size,
            )
        )
    db.add(
        Tick(
            id=1,
            time=datetime.now(UTC),
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            bid=2400.0,
            ask=2400.2,
            last=None,
            volume=0.0,
            source="TEST",
        )
    )
    db.commit()
    return db


def test_torum_params_are_typed_and_cross_validated() -> None:
    params = TorumV1Params.normalize("XAUUSD", {"pullback_entry_min_pct": 0.25, "unlock_timeframe_mode": "BOTH"})

    assert params.session_start == "15:30"
    assert params.pullback_entry_min_pct == 0.25
    assert params.unlock_timeframe_mode == "BOTH"

    with pytest.raises(ValueError):
        TorumV1Params.model_validate({"ath_red_limit_pct": 20, "ath_orange_limit_pct": 10})


def test_ui_schema_exposes_complete_strategy_pipeline() -> None:
    schema = ui_schema()
    groups = {item["key"] for item in schema["groups"]}
    fields = {item["key"] for item in schema["fields"]}

    assert {"market", "unlock", "pullback", "zone", "confirmation", "context", "support", "risk", "execution"} <= groups
    assert {"pullback_entry_min_pct", "unlock_timeframe_mode", "usd_strength_filter_enabled", "risk_max_balance_pct", "take_profit_percent"} <= fields
    hidden = set(schema.get("hidden_fields", []))
    assert set(TorumV1Params.model_fields) == fields | hidden


def test_atomic_bundle_update_versions_and_rejects_stale_revision() -> None:
    db = _session()
    service = StrategyCatalogService(db)
    created = service.update_torum_bundle(
        user_id=1,
        base_params={"pullback_entry_min_pct": 0.20},
        asset_overrides={"XAUUSD": {"session_start": "15:30"}, "XAUEUR": {"session_start": "09:00"}},
        enabled_by_symbol={"XAUUSD": True, "XAUEUR": True},
        mode_by_symbol={"XAUUSD": "PAPER", "XAUEUR": "PAPER"},
        expected_revisions={},
        change_note="initial workbench",
    )
    revisions = {item.internal_symbol: item.revision for item in created}
    before = {item.internal_symbol: dict(item.params_json) for item in list_configs(db, user_id=1)}

    with pytest.raises(ValueError, match="strategy_config_revision_conflict"):
        service.update_torum_bundle(
            user_id=1,
            base_params={"pullback_entry_min_pct": 0.90},
            asset_overrides={},
            enabled_by_symbol={},
            mode_by_symbol={},
            expected_revisions={"XAUUSD": revisions["XAUUSD"] - 1, "XAUEUR": revisions["XAUEUR"]},
            change_note="stale tab",
        )

    after = {item.internal_symbol: dict(item.params_json) for item in list_configs(db, user_id=1)}
    assert after == before
    for config in created:
        versions = list_config_versions(db, config.id)
        assert len(versions) == 1
        assert versions[0].change_note == "initial workbench"


def test_restore_creates_new_revision_without_overwriting_history() -> None:
    db = _session()
    service = StrategyCatalogService(db)
    config = service.update_torum_bundle(
        user_id=1,
        base_params={"pullback_entry_min_pct": 0.20},
        asset_overrides={},
        enabled_by_symbol={"XAUUSD": True},
        mode_by_symbol={"XAUUSD": "PAPER"},
        expected_revisions={},
        change_note="revision one",
    )[1]  # TORUM_SYMBOLS order is XAUEUR, XAUUSD
    original_revision = config.revision
    original_version = db.query(StrategyConfigVersion).filter_by(strategy_config_id=config.id, revision=original_revision).one()

    service.update_config(
        config,
        __import__("app.strategies.schemas", fromlist=["StrategyConfigUpdate"]).StrategyConfigUpdate(
            params_json={**config.params_json, "pullback_entry_min_pct": 0.55},
            expected_revision=original_revision,
            change_note="revision two",
        ),
        user_id=1,
    )
    restored = service.restore_version(config, original_version, user_id=1)

    assert restored.revision == original_revision + 2
    assert restored.params_json["pullback_entry_min_pct"] == 0.20
    assert [item.revision for item in list_config_versions(db, config.id)] == [original_revision + 2, original_revision + 1, original_revision]


def test_replay_never_creates_orders() -> None:
    db = _session()
    config = StrategyCatalogService(db).update_torum_bundle(
        user_id=1,
        base_params={"enabled": True, "usd_strength_strict": False},
        asset_overrides={},
        enabled_by_symbol={"XAUUSD": True},
        mode_by_symbol={"XAUUSD": "PAPER"},
        expected_revisions={},
        change_note="replay",
    )[1]

    result = TorumV1Simulator(db).replay(config, candle_limit=100)

    assert result.signal_count == 0
    assert result.coverage["orders"] == "never executed"
    assert db.query(Order).count() == 0


def test_simulator_never_creates_orders() -> None:
    db = _session()
    config = StrategyCatalogService(db).update_torum_bundle(
        user_id=1,
        base_params={"enabled": True, "usd_strength_strict": False},
        asset_overrides={},
        enabled_by_symbol={"XAUUSD": True},
        mode_by_symbol={"XAUUSD": "PAPER"},
        expected_revisions={},
        change_note="simulator",
    )[1]

    result = TorumV1Simulator(db).simulate(config, candle_limit=100)

    assert result.decision in {"WAIT", "BLOCKED", "BUY"}
    assert result.steps
    assert db.query(Order).count() == 0


def test_manual_lock_state_none_removes_override_and_returns_to_automatic() -> None:
    db = _session()
    service = StrategyCatalogService(db)
    configs = service.update_torum_bundle(
        user_id=1,
        base_params={},
        asset_overrides={"XAUUSD": {"manual_unlock_override": "LOCKED", "manual_unlock_override_day": "2099-01-01"}},
        enabled_by_symbol={"XAUUSD": True},
        mode_by_symbol={"XAUUSD": "PAPER"},
        expected_revisions={},
        change_note="manual lock test",
    )
    user = db.get(User, 1)
    assert user is not None

    set_torum_v1_manual_lock_state(
        TorumV1ManualLockStateUpdate(symbol="XAUUSD", unlocked=None),
        db=db,
        current_user=user,
    )

    xauusd = next(item for item in list_configs(db, user_id=1) if item.internal_symbol == "XAUUSD")
    assert "manual_unlock_override" not in xauusd.params_json
    assert "manual_unlock_override_day" not in xauusd.params_json
    assert xauusd.revision > configs[1].revision - 1

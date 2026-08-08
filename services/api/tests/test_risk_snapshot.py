from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.db.base import Base
from app.mt5.schemas import MT5AccountPayload, MT5StatusPayload
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.positions.models import Position
from app.risk.snapshot import RiskSnapshotService, clear_risk_snapshot_cache
from app.strategies.ath import plan_torum_v1_bot_exposure
from app.strategies.models import StrategySignal
from app.symbols.models import SymbolMapping
from app.symbols.service import get_symbol_by_internal
from app.users.models import User  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_mt5_status() -> None:
    clear_risk_snapshot_cache()
    mt5_status_store.update(MT5StatusPayload())
    yield
    clear_risk_snapshot_cache()
    mt5_status_store.update(MT5StatusPayload())


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = testing_session()
    db.add(
        SymbolMapping(
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            display_name="XAUUSD",
            enabled=True,
            asset_class="METAL",
            tradable=True,
            analysis_only=False,
            digits=2,
            point=0.01,
            contract_size=100.0,
        )
    )
    db.add(
        Candle(
            time=datetime(2026, 5, 1, tzinfo=UTC),
            internal_symbol="XAUUSD",
            timeframe="H1",
            open=4900.0,
            high=5000.0,
            low=4800.0,
            close=4900.0,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )
    db.commit()
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="DEMO",
            account=MT5AccountPayload(balance=10000.0, equity=10000.0, trade_mode="DEMO"),
        )
    )
    return db


def _position(db: Session, *, order_id: int | None, volume: float, open_price: float) -> None:
    db.add(
        Position(
            user_id=1,
            order_id=order_id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="DEMO",
            account_login=1,
            account_server="test",
            side="BUY",
            volume=volume,
            open_price=open_price,
            current_price=open_price,
            sl=None,
            tp=None,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=123456 + int(volume * 1000),
            magic_number=260426,
            opened_at=datetime(2026, 5, 1, tzinfo=UTC),
            raw_payload_json={},
        )
    )
    db.commit()


def _stale_demo_position_without_ticket(db: Session, *, order_id: int | None = None) -> None:
    db.add(
        Position(
            user_id=1,
            order_id=order_id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="DEMO",
            account_login=1,
            account_server="test",
            side="BUY",
            volume=0.04,
            open_price=4700.0,
            current_price=4700.0,
            sl=None,
            tp=None,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=None,
            magic_number=260426,
            opened_at=datetime(2026, 5, 1, tzinfo=UTC),
            raw_payload_json={},
        )
    )
    db.commit()


def _bot_order(db: Session, *, volume: float = 0.01) -> Order:
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=1,
        account_server="test",
        side="BUY",
        order_type="MARKET",
        volume=volume,
        status="EXECUTED",
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _pending_bot_order(db: Session, *, volume: float, requested_price: float, status: str = "SENT") -> Order:
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=1,
        account_server="test",
        side="BUY",
        order_type="MARKET",
        volume=volume,
        requested_price=requested_price,
        status=status,
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _trading_settings() -> SimpleNamespace:
    return SimpleNamespace(
        lot_per_equity_enabled=True,
        equity_per_0_01_lot=2500.0,
        minimum_lot=0.01,
    )


def test_risk_snapshot_uses_ath_stress_and_cached_candidate_loss() -> None:
    db = _session()
    _position(db, order_id=None, volume=0.04, open_price=4700.0)

    snapshot = RiskSnapshotService(db).recompute("XAUUSD")
    preview = RiskSnapshotService(db).preview_candidate("XAUUSD", side="BUY", volume=0.01, price=4600.0)

    assert snapshot.stress_price == 3500.0
    assert snapshot.balance == 10000.0
    assert snapshot.current_loss == 4800.0
    assert snapshot.remaining_risk == 200.0
    assert preview.candidate_loss == 1100.0
    assert preview.projected_loss == 5900.0
    assert preview.breaches_limit is True


def test_risk_snapshot_ignores_stale_demo_positions_without_mt5_ticket() -> None:
    db = _session()
    _stale_demo_position_without_ticket(db)

    snapshot = RiskSnapshotService(db).recompute("XAUUSD")
    preview = RiskSnapshotService(db).preview_candidate("XAUUSD", side="BUY", volume=0.01, price=4600.0)

    assert snapshot.positions_count == 0
    assert snapshot.current_loss == 0.0
    assert snapshot.remaining_risk == 5000.0
    assert preview.candidate_loss == 1100.0
    assert preview.projected_loss == 1100.0
    assert preview.breaches_limit is False


def test_strategy_snapshot_counts_only_torum_v1_bot_positions() -> None:
    db = _session()
    _position(db, order_id=None, volume=0.04, open_price=4700.0)
    order = _bot_order(db)
    _position(db, order_id=order.id, volume=0.01, open_price=4600.0)

    all_snapshot = RiskSnapshotService(db).recompute("XAUUSD")
    strategy_snapshot = RiskSnapshotService(db).recompute("XAUUSD", source="STRATEGY")

    assert all_snapshot.positions_count == 2
    assert all_snapshot.current_loss == 5900.0
    assert strategy_snapshot.positions_count == 1
    assert strategy_snapshot.current_loss == 1100.0


def test_torum_v1_plan_blocks_ath_red_zone() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=1,
        current_price=4900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is False
    assert plan.reason == "ath_red_zone"


def test_torum_v1_plan_green_allows_three_equivalents_when_risk_fits() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=3,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 3
    assert plan.volume == 0.12


def test_torum_v1_plan_degrades_when_risk_exceeds_limit() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=3,
        current_price=4000.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 2


def test_torum_v1_plan_does_not_reduce_s3_when_degrade_is_disabled() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=3,
        current_price=4000.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
        strategy_params={"support_degrade_enabled": False},
    )

    assert plan.allowed is False
    assert plan.multiplier == 0
    assert plan.reason == "risk_limit_exceeded"


def test_torum_v1_plan_counts_only_bot_positions_not_manual() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    _position(db, order_id=None, volume=0.04, open_price=4700.0)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=1,
        current_price=4600.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.open_lot_equivalents == 0.0


def test_torum_v1_plan_ignores_stale_demo_bot_positions_without_mt5_ticket() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    order = _bot_order(db, volume=0.04)
    _stale_demo_position_without_ticket(db, order_id=order.id)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=2,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 2
    assert plan.open_lot_equivalents == 0.0


def test_torum_v1_plan_counts_pending_bot_orders_for_capacity() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    _pending_bot_order(db, volume=0.08, requested_price=3900.0)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=2,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 1
    assert plan.open_lot_equivalents == 2.0
    assert plan.potential_loss == 4800.0


def test_torum_v1_plan_excludes_current_pending_order_from_capacity() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    order = _pending_bot_order(db, volume=0.08, requested_price=3900.0)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=2,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
        exclude_order_id=order.id,
    )

    assert plan.allowed is True
    assert plan.multiplier == 2
    assert plan.open_lot_equivalents == 0.0
    assert plan.potential_loss == 3200.0


def test_torum_v1_plan_blocks_when_pending_orders_use_all_equivalents() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    _pending_bot_order(db, volume=0.12, requested_price=3900.0)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=1,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is False
    assert plan.reason == "risk_or_ath_capacity_exceeded"
    assert plan.open_lot_equivalents == 3.0


def test_torum_v1_plan_blocks_when_pending_order_risk_exceeds_limit() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    _pending_bot_order(db, volume=0.08, requested_price=4000.0)

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=1,
        current_price=4000.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is False
    assert plan.reason == "risk_or_ath_capacity_exceeded"
    assert plan.open_lot_equivalents == 2.0


def test_torum_v1_plan_ignores_stale_pre_broker_orders_for_capacity() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    order = _pending_bot_order(db, volume=0.12, requested_price=3900.0, status="CREATED")
    order.created_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=3,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 3
    assert plan.open_lot_equivalents == 0.0


def test_torum_v1_plan_ignores_stale_reserved_signals_for_capacity() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.8,
        suggested_volume=0.12,
        reason="test_stale_reservation",
        metadata_json={"accepted_volume": 0.12, "accepted_multiplier": 3},
        status="RISK_APPROVED",
        created_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db.add(signal)
    db.commit()

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=3,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 3
    assert plan.open_lot_equivalents == 0.0


def test_torum_v1_plan_does_not_double_count_signal_and_its_pending_order() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.9,
        suggested_volume=0.08,
        reason="pending_order_same_reservation",
        metadata_json={"accepted_volume": 0.08, "accepted_multiplier": 2},
        status="SENT_TO_ORDER_MANAGER",
    )
    db.add(signal)
    db.flush()
    order = _pending_bot_order(db, volume=0.08, requested_price=3900.0)
    order.strategy_signal_id = signal.id
    signal.order_id = order.id
    db.commit()

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=1,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=_trading_settings(),
        symbol_mapping=mapping,
    )

    assert plan.allowed is True
    assert plan.multiplier == 1
    assert plan.open_lot_equivalents == 2.0


def test_torum_v1_plan_conservatively_counts_open_position_with_missing_account_identity() -> None:
    db = _session()
    mapping = get_symbol_by_internal(db, "XAUUSD")
    order = _bot_order(db, volume=0.08)
    db.add(
        Position(
            user_id=1,
            order_id=order.id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="DEMO",
            account_login=None,
            account_server=None,
            side="BUY",
            volume=0.08,
            open_price=3900.0,
            current_price=3900.0,
            sl=None,
            tp=3903.51,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=987654,
            mt5_position_identifier=987654,
            magic_number=260426,
            opened_at=datetime.now(UTC),
            raw_payload_json={},
        )
    )
    db.commit()
    scoped_settings = SimpleNamespace(
        trading_mode="DEMO",
        lot_per_equity_enabled=True,
        equity_per_0_01_lot=2500.0,
        minimum_lot=0.01,
    )

    plan = plan_torum_v1_bot_exposure(
        db,
        symbol="XAUUSD",
        user_id=1,
        desired_multiplier=2,
        current_price=3900.0,
        balance=10000.0,
        trading_settings=scoped_settings,
        symbol_mapping=mapping,
        account_login=123456,
        account_server="Broker-Demo",
    )

    assert plan.allowed is True
    assert plan.multiplier == 1
    assert plan.open_lot_equivalents == 2.0


def test_ambiguous_broker_order_keeps_capacity_beyond_normal_pipeline_ttl() -> None:
    from app.strategies.ath import _active_pending_orders

    db = _session()
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=1,
        account_server="test",
        side="BUY",
        order_type="MARKET",
        volume=0.09,
        requested_price=3500.0,
        status="RECONCILING",
        magic_number=260426,
        comment="Torum s123",
        source="STRATEGY",
        strategy_key="torum_v1",
        created_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db.add(order)
    db.commit()

    active = _active_pending_orders(
        db,
        "XAUUSD",
        1,
        mode="DEMO",
        account_login=1,
        account_server="test",
    )

    assert [item.id for item in active] == [order.id]

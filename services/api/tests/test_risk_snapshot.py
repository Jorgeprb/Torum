from datetime import UTC, datetime

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
from app.risk.snapshot import RiskSnapshotService
from app.symbols.models import SymbolMapping


@pytest.fixture(autouse=True)
def _reset_mt5_status() -> None:
    mt5_status_store.update(MT5StatusPayload())
    yield
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


def test_strategy_snapshot_counts_only_torum_v1_bot_positions() -> None:
    db = _session()
    _position(db, order_id=None, volume=0.04, open_price=4700.0)
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=1,
        account_server="test",
        side="BUY",
        order_type="MARKET",
        volume=0.01,
        status="EXECUTED",
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    _position(db, order_id=order.id, volume=0.01, open_price=4600.0)

    all_snapshot = RiskSnapshotService(db).recompute("XAUUSD")
    strategy_snapshot = RiskSnapshotService(db).recompute("XAUUSD", source="STRATEGY")

    assert all_snapshot.positions_count == 2
    assert all_snapshot.current_loss == 5900.0
    assert strategy_snapshot.positions_count == 1
    assert strategy_snapshot.current_loss == 1100.0

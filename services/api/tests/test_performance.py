from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
from app.mt5.schemas import MT5AccountPayload, MT5StatusPayload
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.performance.models import CapitalMovement
from app.performance.service import PerformanceService
from app.positions.models import Position
from app.users.models import User, UserRole


@pytest.fixture(autouse=True)
def _reset_mt5_status():
    mt5_status_store.update(MT5StatusPayload())
    yield
    mt5_status_store.update(MT5StatusPayload())


def _db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session) -> User:
    user = User(
        username="performance-user",
        email="performance@example.com",
        hashed_password="x",
        role=UserRole.trader,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _strategy_trade(db: Session, user: User, *, closed_at: datetime, profit: float, position_id: int) -> None:
    order = Order(
        user_id=user.id,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="LIVE",
        account_login=123,
        account_server="Broker",
        side="BUY",
        order_type="MARKET",
        volume=0.03,
        status="EXECUTED",
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.flush()
    db.add(
        Position(
            id=position_id,
            user_id=user.id,
            order_id=order.id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="LIVE",
            account_login=123,
            account_server="Broker",
            side="BUY",
            volume=0.03,
            open_price=4000,
            close_price=4010,
            profit=profit,
            swap=0,
            commission=0,
            fee=0,
            status="CLOSED",
            opened_at=closed_at,
            closed_at=closed_at,
        )
    )
    db.commit()


def test_twr_neutralizes_capital_injection() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=23000, trade_mode="REAL"),
        )
    )
    db.add_all(
        [
            CapitalMovement(
                user_id=user.id,
                account_login=123,
                account_server="Broker",
                currency="EUR",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                amount=10000,
                kind="INITIAL",
                source="MANUAL",
            ),
            CapitalMovement(
                user_id=user.id,
                account_login=123,
                account_server="Broker",
                currency="EUR",
                occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
                amount=10000,
                kind="DEPOSIT",
                source="MANUAL",
            ),
        ]
    )
    db.commit()
    _strategy_trade(db, user, closed_at=datetime(2026, 1, 10, tzinfo=UTC), profit=1000, position_id=1)
    _strategy_trade(db, user, closed_at=datetime(2026, 1, 20, tzinfo=UTC), profit=2000, position_id=2)

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 1, 1, tzinfo=UTC),
        to_time=datetime(2026, 1, 31, 23, 59, tzinfo=UTC),
    )

    # 10% first sub-period, then 2000 / 21000 = 9.5238%; deposit itself adds zero return.
    assert report.return_pct is not None
    assert round(report.return_pct, 4) == 20.4762
    assert report.net_profit == 3000
    assert report.cash_flow == 10000
    assert report.capital_start == 10000
    assert report.capital_end == 23000
    assert report.trades == 2
    assert report.win_rate_pct == 100


def test_only_torum_strategy_orders_are_counted() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10100, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=123,
            account_server="Broker",
            currency="EUR",
            occurred_at=datetime(2026, 2, 1, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )
    db.commit()
    _strategy_trade(db, user, closed_at=datetime(2026, 2, 2, tzinfo=UTC), profit=100, position_id=10)

    manual = Order(
        user_id=user.id,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="LIVE",
        account_login=123,
        account_server="Broker",
        side="BUY",
        order_type="MARKET",
        volume=0.03,
        status="EXECUTED",
        source="MANUAL",
    )
    db.add(manual)
    db.flush()
    db.add(
        Position(
            user_id=user.id,
            order_id=manual.id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="LIVE",
            account_login=123,
            account_server="Broker",
            side="BUY",
            volume=0.03,
            open_price=4000,
            close_price=4100,
            profit=5000,
            status="CLOSED",
            opened_at=datetime(2026, 2, 3, tzinfo=UTC),
            closed_at=datetime(2026, 2, 3, tzinfo=UTC),
        )
    )
    db.commit()

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 2, 1, tzinfo=UTC),
        to_time=datetime(2026, 2, 28, tzinfo=UTC),
    )
    assert report.net_profit == 100
    assert report.trades == 1
    assert round(report.return_pct or 0, 4) == 1.0


def test_mt5_cash_flow_import_is_idempotent() -> None:
    db = _db()
    _user(db)
    service = PerformanceService(db)
    account = MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=12000, trade_mode="REAL")
    flow = {
        "ticket": 555,
        "time_msc": int(datetime(2026, 3, 2, tzinfo=UTC).timestamp() * 1000),
        "profit": 2000,
        "cash_flow_kind": "DEPOSIT",
        "deal_type_name": "BALANCE",
        "comment": "Bank transfer",
    }

    assert service.sync_mt5_capital_flows([flow], account) == 1
    assert service.sync_mt5_capital_flows([flow], account) == 0
    rows = list(db.query(CapitalMovement).all())
    assert len(rows) == 1
    assert rows[0].amount == 2000
    assert rows[0].source == "MT5"


def test_mt5_broker_chart_cash_flow_time_is_normalized_to_real_utc() -> None:
    db = _db()
    _user(db)
    service = PerformanceService(db)
    account = MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=12000, trade_mode="REAL")

    broker_wall_as_epoch = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
    flow = {
        "ticket": 556,
        "time_msc": int(broker_wall_as_epoch.timestamp() * 1000),
        "time_domain": "BROKER_CHART",
        "profit": 2000,
        "cash_flow_kind": "DEPOSIT",
    }

    assert service.sync_mt5_capital_flows([flow], account) == 1
    movement = db.scalar(select(CapitalMovement).where(CapitalMovement.external_id == 556))
    assert movement is not None
    broker_zone = ZoneInfo(get_settings().chart_broker_time_zone)
    expected = broker_wall_as_epoch.replace(tzinfo=None).replace(tzinfo=broker_zone).astimezone(UTC)
    assert movement.occurred_at.replace(tzinfo=UTC) == expected


def test_mt5_import_reconciles_matching_manual_movement_instead_of_double_counting() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=12000, trade_mode="REAL"),
        )
    )
    manual = CapitalMovement(
        user_id=user.id,
        account_login=123,
        account_server="Broker",
        currency="EUR",
        occurred_at=datetime(2026, 7, 31, 12, 5, tzinfo=UTC),
        amount=2000,
        kind="DEPOSIT",
        source="MANUAL",
        note="Aportación",
    )
    db.add(manual)
    db.commit()

    broker_zone = ZoneInfo(get_settings().chart_broker_time_zone)
    broker_wall_as_epoch = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
    normalized = broker_wall_as_epoch.replace(tzinfo=None).replace(tzinfo=broker_zone).astimezone(UTC)
    manual.occurred_at = normalized + timedelta(minutes=5)
    db.commit()

    flow = {
        "ticket": 557,
        "time_msc": int(broker_wall_as_epoch.timestamp() * 1000),
        "time_domain": "BROKER_CHART",
        "profit": 2000,
        "cash_flow_kind": "DEPOSIT",
        "comment": "Bank transfer",
    }

    assert PerformanceService(db).sync_mt5_capital_flows([flow], MT5AccountPayload(login=123, server="Broker", currency="EUR")) == 1
    rows = list(db.query(CapitalMovement).all())
    assert len(rows) == 1
    assert rows[0].source == "MT5"
    assert rows[0].external_id == 557
    assert rows[0].occurred_at.replace(tzinfo=UTC) == normalized
    assert rows[0].note == "Aportación"


def test_manual_capital_from_another_mt5_account_is_not_mixed_into_report() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10000, trade_mode="REAL"),
        )
    )
    db.add_all(
        [
            CapitalMovement(
                user_id=user.id,
                account_login=123,
                account_server="Broker",
                currency="EUR",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                amount=10000,
                kind="INITIAL",
                source="MANUAL",
            ),
            CapitalMovement(
                user_id=user.id,
                account_login=999,
                account_server="OtherBroker",
                currency="EUR",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                amount=50000,
                kind="INITIAL",
                source="MANUAL",
            ),
        ]
    )
    db.commit()

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 1, 1, tzinfo=UTC),
        to_time=datetime(2026, 1, 31, tzinfo=UTC),
    )

    assert report.capital_start == 10000
    assert all(item.account_login != 999 for item in report.capital_movements)


def test_twr_can_start_when_initial_capital_arrives_inside_selected_period() -> None:
    db = _db()
    user = _user(db)
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=None,
            account_server=None,
            currency="EUR",
            occurred_at=datetime(2026, 1, 5, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )
    db.commit()
    _strategy_trade(db, user, closed_at=datetime(2026, 1, 10, tzinfo=UTC), profit=1000, position_id=50)

    # Deliberately no current MT5 balance: the explicit ledger must still be
    # sufficient even though the selected dates start before funding.
    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 1, 1, tzinfo=UTC),
        to_time=datetime(2026, 1, 31, tzinfo=UTC),
    )

    assert report.capital_start == 0
    assert round(report.return_pct or 0, 4) == 10.0
    assert report.capital_end == 11000

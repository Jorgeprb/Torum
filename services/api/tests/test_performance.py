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
from app.strategies.models import StrategySignal
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


def _strategy_trade(
    db: Session,
    user: User,
    *,
    closed_at: datetime,
    profit: float,
    position_id: int,
    symbol: str = "XAUUSD",
    multiplier: int = 1,
    volume: float | None = None,
) -> None:
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=user.id,
        internal_symbol=symbol,
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=1.0,
        suggested_volume=volume or 0.03 * multiplier,
        reason="performance test",
        metadata_json={"accepted_multiplier": multiplier},
        status="EXECUTED",
    )
    db.add(signal)
    db.flush()
    trade_volume = volume or 0.03 * multiplier
    order = Order(
        user_id=user.id,
        internal_symbol=symbol,
        broker_symbol=symbol,
        mode="LIVE",
        account_login=123,
        account_server="Broker",
        side="BUY",
        order_type="MARKET",
        volume=trade_volume,
        status="EXECUTED",
        source="STRATEGY",
        strategy_key="torum_v1",
        strategy_signal_id=signal.id,
    )
    db.add(order)
    db.flush()
    db.add(
        Position(
            id=position_id,
            user_id=user.id,
            order_id=order.id,
            internal_symbol=symbol,
            broker_symbol=symbol,
            mode="LIVE",
            account_login=123,
            account_server="Broker",
            side="BUY",
            volume=trade_volume,
            open_price=4000,
            close_price=4010,
            profit=profit,
            swap=0,
            commission=0,
            fee=0,
            status="CLOSED",
            opened_at=closed_at - timedelta(minutes=35),
            closed_at=closed_at,
        )
    )
    db.commit()


def test_open_strategy_position_never_counts_until_realized_close() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10000, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=123,
            account_server="Broker",
            currency="EUR",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )
    order = Order(
        user_id=user.id,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="LIVE",
        account_login=123,
        account_server="Broker",
        side="BUY",
        order_type="MARKET",
        volume=0.04,
        status="EXECUTED",
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.flush()
    position = Position(
        user_id=user.id,
        order_id=order.id,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="LIVE",
        account_login=123,
        account_server="Broker",
        side="BUY",
        volume=0.04,
        open_price=4000,
        current_price=4100,
        # Deliberately large floating P/L: it must still contribute nothing.
        profit=4000,
        swap=0,
        commission=0,
        fee=0,
        status="OPEN",
        opened_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )
    db.add(position)
    db.commit()

    service = PerformanceService(db)
    before_close = service.report(
        user,
        from_time=datetime(2026, 8, 1, tzinfo=UTC),
        to_time=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
    )
    assert before_close.trades == 0
    assert before_close.net_profit == 0
    assert before_close.return_pct == 0

    # Only the realized close is allowed to enter performance, and the exact
    # realized amount (positive, negative, small or large) is what is counted.
    position.status = "CLOSED"
    position.close_price = 3990
    position.current_price = 3990
    position.profit = -40
    position.commission = -2
    position.closed_at = datetime(2026, 8, 10, 13, 0, tzinfo=UTC)
    db.commit()

    after_close = service.report(
        user,
        from_time=datetime(2026, 8, 1, tzinfo=UTC),
        to_time=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
    )
    assert after_close.trades == 1
    assert after_close.net_profit == -42
    assert round(after_close.return_pct or 0, 4) == -0.42


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


def test_all_closed_account_trades_are_counted_not_only_strategy() -> None:
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
    assert report.net_profit == 5100
    assert report.trades == 2
    assert round(report.return_pct or 0, 4) == 51.0


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


def test_daily_calendar_and_multiplier_breakdown_are_realized_and_grouped() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10180, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=123,
            account_server="Broker",
            currency="EUR",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )
    db.commit()

    _strategy_trade(db, user, closed_at=datetime(2026, 8, 10, 9, 30, tzinfo=UTC), profit=120, position_id=201, multiplier=2)
    _strategy_trade(db, user, closed_at=datetime(2026, 8, 10, 13, 15, tzinfo=UTC), profit=-40, position_id=202, symbol="XAUEUR", multiplier=1)
    _strategy_trade(db, user, closed_at=datetime(2026, 8, 11, 8, 10, tzinfo=UTC), profit=100, position_id=203, multiplier=3)

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 8, 1, tzinfo=UTC),
        to_time=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
    )

    assert report.trades == 3
    assert report.net_profit == 180
    assert report.profit_factor == 5.5
    assert report.expectancy == 60
    assert report.max_win_streak == 1
    assert report.max_loss_streak == 1
    assert len(report.days) == 2

    first_day = report.days[0]
    assert first_day.trades == 2
    assert first_day.net_profit == 80
    assert round(first_day.return_pct or 0, 4) == 0.8
    assert first_day.x1 == 1
    assert first_day.x2 == 1
    assert first_day.x3 == 0
    assert first_day.xauusd == 1
    assert first_day.xaueur == 1
    assert [trade.multiplier for trade in first_day.trades_detail] == [2, 1]

    by_multiplier = {item.key: item for item in report.multiplier_breakdown}
    assert by_multiplier["x1"].trades == 1
    assert by_multiplier["x2"].trades == 1
    assert by_multiplier["x3"].trades == 1
    assert by_multiplier["x2"].net_profit == 120

    by_symbol = {item.key: item for item in report.symbol_breakdown}
    assert by_symbol["XAUUSD"].trades == 2
    assert by_symbol["XAUEUR"].trades == 1


def test_performance_matches_history_count_across_strategy_manual_and_imported_trades() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10270, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=123,
            account_server="Broker",
            currency="EUR",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )
    db.commit()

    # Two automatic Torum trades.
    _strategy_trade(db, user, closed_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC), profit=40, position_id=301, multiplier=2, volume=0.08)
    _strategy_trade(db, user, closed_at=datetime(2026, 8, 27, 12, 20, tzinfo=UTC), profit=30, position_id=302, multiplier=1, volume=0.04)

    # Four orders opened manually from Torum. New manual requests persist their
    # exact multiplier in request_payload_json.
    for index, (volume, multiplier, profit) in enumerate(((0.04, 1, 20), (0.08, 2, 30), (0.12, 3, 50), (0.04, 1, -10)), start=303):
        order = Order(
            user_id=user.id,
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            mode="LIVE",
            account_login=123,
            account_server="Broker",
            side="BUY",
            order_type="MARKET",
            volume=volume,
            status="EXECUTED",
            source="MANUAL",
            request_payload_json={"multiplier": multiplier},
        )
        db.add(order)
        db.flush()
        closed = datetime(2026, 8, 27, 13, index - 303, tzinfo=UTC)
        db.add(
            Position(
                id=index,
                user_id=user.id,
                order_id=order.id,
                internal_symbol="XAUUSD",
                broker_symbol="XAUUSD",
                mode="LIVE",
                account_login=123,
                account_server="Broker",
                side="BUY",
                volume=volume,
                open_price=4000,
                close_price=4010,
                profit=profit,
                swap=0,
                commission=0,
                fee=0,
                status="CLOSED",
                opened_at=closed - timedelta(minutes=15),
                closed_at=closed,
            )
        )

    # Three positions imported from MT5 with no Torum Order at all. They still
    # belong to the same account/history and therefore must count.
    for index, (symbol, volume, profit) in enumerate((("XAUEUR", 0.04, 25), ("XAUEUR", 0.08, 35), ("XAUUSD", 0.04, 50)), start=307):
        closed = datetime(2026, 8, 27, 14, index - 307, tzinfo=UTC)
        db.add(
            Position(
                id=index,
                user_id=user.id,
                order_id=None,
                internal_symbol=symbol,
                broker_symbol=symbol,
                mode="LIVE",
                account_login=123,
                account_server="Broker",
                side="BUY",
                volume=volume,
                open_price=4000,
                close_price=4010,
                profit=profit,
                swap=0,
                commission=0,
                fee=0,
                status="CLOSED",
                opened_at=closed - timedelta(minutes=10),
                closed_at=closed,
            )
        )
    # A tenth closed position on another MT5 account must not leak into the
    # active account's calendar or percentage.
    db.add(
        Position(
            id=399, user_id=user.id, order_id=None, internal_symbol="XAUUSD", broker_symbol="XAUUSD",
            mode="LIVE", account_login=999, account_server="OtherBroker", side="BUY", volume=0.40,
            open_price=4000, close_price=4500, profit=9999, swap=0, commission=0, fee=0, status="CLOSED",
            opened_at=datetime(2026, 8, 27, 15, 0, tzinfo=UTC), closed_at=datetime(2026, 8, 27, 15, 5, tzinfo=UTC),
        )
    )
    db.commit()

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
        to_time=datetime(2026, 8, 28, 23, 59, tzinfo=UTC),
    )

    assert report.trades == 9
    assert report.pending_trades == 0
    assert sum(day.trades for day in report.days) == 9
    assert sum(item.trades for item in report.symbol_breakdown) == 9
    by_multiplier = {item.key: item for item in report.multiplier_breakdown}
    assert by_multiplier["x1"].trades == 5
    assert by_multiplier["x2"].trades == 3
    assert by_multiplier["x3"].trades == 1


def test_calendar_uses_madrid_day_not_broker_wall_clock_day() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10010, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id,
            account_login=123,
            account_server="Broker",
            currency="EUR",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            amount=10000,
            kind="INITIAL",
            source="MANUAL",
        )
    )

    # Stored live MT5 time 00:30 on Aug 28 is broker wall clock (UTC+3), so the
    # real instant is Aug 27 21:30 UTC / 23:30 Europe/Madrid.
    order = Order(
        user_id=user.id, internal_symbol="XAUUSD", broker_symbol="XAUUSD", mode="LIVE",
        account_login=123, account_server="Broker", side="BUY", order_type="MARKET",
        volume=0.04, status="EXECUTED", source="MANUAL", request_payload_json={"multiplier": 1},
    )
    db.add(order)
    db.flush()
    db.add(
        Position(
            user_id=user.id, order_id=order.id, internal_symbol="XAUUSD", broker_symbol="XAUUSD",
            mode="LIVE", account_login=123, account_server="Broker", side="BUY", volume=0.04,
            open_price=4000, close_price=4001, profit=10, swap=0, commission=0, fee=0, status="CLOSED",
            opened_at=datetime(2026, 8, 28, 0, 0, tzinfo=UTC),
            closed_at=datetime(2026, 8, 28, 0, 30, tzinfo=UTC),
        )
    )
    db.commit()

    report = PerformanceService(db).report(
        user,
        from_time=datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
        to_time=datetime(2026, 8, 28, 23, 59, tzinfo=UTC),
    )
    assert len(report.days) == 1
    assert report.days[0].date.isoformat() == "2026-08-27"
    assert report.days[0].trades == 1
    assert report.days[0].trades_detail[0].closed_at.astimezone(ZoneInfo("Europe/Madrid")).hour == 23


def test_pending_closed_trade_is_visible_in_calendar_but_not_in_return_until_enriched() -> None:
    db = _db()
    user = _user(db)
    mt5_status_store.update(
        MT5StatusPayload(
            connected_to_mt5=True,
            account_trade_mode="REAL",
            account=MT5AccountPayload(login=123, server="Broker", currency="EUR", balance=10000, trade_mode="REAL"),
        )
    )
    db.add(
        CapitalMovement(
            user_id=user.id, account_login=123, account_server="Broker", currency="EUR",
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC), amount=10000, kind="INITIAL", source="MANUAL",
        )
    )
    order = Order(
        user_id=user.id, internal_symbol="XAUUSD", broker_symbol="XAUUSD", mode="LIVE", account_login=123,
        account_server="Broker", side="BUY", order_type="MARKET", volume=0.04, status="EXECUTED", source="MANUAL",
        request_payload_json={"multiplier": 1},
    )
    db.add(order)
    db.flush()
    db.add(
        Position(
            user_id=user.id, order_id=order.id, internal_symbol="XAUUSD", broker_symbol="XAUUSD", mode="LIVE",
            account_login=123, account_server="Broker", side="BUY", volume=0.04, open_price=4000, close_price=4005,
            profit=20, status="CLOSED", enrichment_status="CLOSED_PENDING_MT5",
            opened_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC), closed_at=datetime(2026, 8, 27, 12, 30, tzinfo=UTC),
        )
    )
    db.commit()

    report = PerformanceService(db).report(
        user, from_time=datetime(2026, 8, 27, tzinfo=UTC), to_time=datetime(2026, 8, 28, tzinfo=UTC)
    )
    assert report.trades == 1
    assert report.pending_trades == 1
    assert report.net_profit == 0
    assert report.return_pct == 0
    assert report.days[0].trades == 1
    assert report.days[0].pending == 1
    assert report.days[0].trades_detail[0].pending is True
    assert report.days[0].trades_detail[0].net_profit is None

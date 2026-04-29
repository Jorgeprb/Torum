from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.orders.models import Order
from app.orders.router import router as orders_router
from app.orders.service import OrderManager
from app.positions.models import Position
from app.positions.router import router as positions_router
from app.positions.service import PositionService
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trade_history.routes import router as trade_history_router
from app.trading.schemas import ManualOrderRequest
from app.users.models import User, UserRole


def _settings(mode: str = "PAPER", live_enabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        trading_mode=mode,
        live_trading_enabled=live_enabled,
        require_live_confirmation=True,
        max_order_volume=1.0,
        allow_market_orders=True,
        is_paused=False,
    )


def _symbol(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(internal_symbol="XAUUSD", broker_symbol="XAUUSD", enabled=enabled)


def _tick() -> SimpleNamespace:
    return SimpleNamespace(time=datetime.now(UTC), bid=2325.0, ask=2325.2, last=None)


def _mt5_status(mode: str = "UNKNOWN", connected: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        connected_to_mt5=connected,
        account_trade_mode=mode,
        updated_at=datetime.now(UTC),
    )


class DummyRiskManager(RiskManager):
    def __init__(self, tick: SimpleNamespace | None) -> None:
        self._tick = tick

    def latest_tick(self, internal_symbol: str) -> SimpleNamespace | None:
        return self._tick

    def _apply_news_zone_rules(self, internal_symbol: str, reasons: list[str], warnings: list[str]) -> None:
        return None


def test_risk_manager_allows_paper_without_mt5() -> None:
    order = ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01)

    decision = DummyRiskManager(_tick()).evaluate(
        order=order,
        trading_settings=_settings("PAPER"),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status(),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is True
    assert decision.reasons == []


def test_risk_manager_blocks_demo_when_account_is_real() -> None:
    order = ManualOrderRequest(
        internal_symbol="XAUUSD",
        side="BUY",
        volume=0.01,
        client_confirmation={"confirmed": True, "mode_acknowledged": "DEMO"},
    )

    decision = DummyRiskManager(_tick()).evaluate(
        order=order,
        trading_settings=_settings("DEMO"),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status("REAL", connected=True),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "does not match configured mode DEMO" in "; ".join(decision.reasons)


def test_risk_manager_blocks_live_when_not_enabled() -> None:
    order = ManualOrderRequest(
        internal_symbol="XAUUSD",
        side="BUY",
        volume=0.01,
        client_confirmation={"confirmed": True, "mode_acknowledged": "LIVE", "live_text": "CONFIRM LIVE"},
    )

    decision = DummyRiskManager(_tick()).evaluate(
        order=order,
        trading_settings=_settings("LIVE", live_enabled=False),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status("REAL", connected=True),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "LIVE trading is disabled" in decision.reasons


def test_risk_manager_rejects_invalid_volume() -> None:
    order = ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0)

    decision = DummyRiskManager(_tick()).evaluate(
        order=order,
        trading_settings=_settings("PAPER"),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status(),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "Volume must be greater than zero" in decision.reasons


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
        User(
            id=1,
            username="admin",
            email="admin@example.com",
            hashed_password="test",
            role=UserRole.admin,
            is_active=True,
        )
    )
    db.add(
        SymbolMapping(
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            display_name="Gold / USD",
            enabled=True,
            digits=2,
            point=0.01,
            contract_size=100.0,
        )
    )
    db.add(
        TradingSettings(
            user_id=None,
            trading_mode="PAPER",
            live_trading_enabled=False,
            require_live_confirmation=True,
            default_volume=0.01,
            default_magic_number=260426,
            default_deviation_points=20,
            max_order_volume=1.0,
            allow_market_orders=True,
            allow_pending_orders=False,
        )
    )
    db.add(
        Tick(
            id=1,
            time=datetime.now(UTC),
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            bid=2325.0,
            ask=2325.2,
            last=None,
            volume=0.0,
            source="TEST",
        )
    )
    db.commit()
    return db


def test_order_manager_creates_paper_order_and_position() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None

    response = OrderManager(db).create_manual_order(
        ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01),
        user,
    )

    assert response.ok is True
    assert response.status == "EXECUTED"
    assert db.query(Order).count() == 1
    assert db.query(Position).count() == 1


def test_position_service_profit_uses_contract_size() -> None:
    db = _session()
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="PAPER",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.02,
        open_price=2324.0,
        current_price=2324.0,
        sl=None,
        tp=2326.0,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=None,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    updated = PositionService(db).list_with_prices(status="OPEN", symbol="XAUUSD", limit=10)[0]

    assert updated.current_price == 2325.0
    assert round(updated.profit or 0, 2) == 2.0


def test_orders_manual_endpoint_accepts_valid_paper_payload() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    app = FastAPI()
    app.include_router(orders_router, prefix="/api")

    def override_db() -> Session:
        return db

    app.dependency_overrides[get_db] = lambda: override_db()
    app.dependency_overrides[get_current_user] = lambda: user

    client = TestClient(app)
    response = client.post(
        "/api/orders/manual",
        json={"internal_symbol": "XAUUSD", "side": "BUY", "order_type": "MARKET", "volume": 0.01},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "EXECUTED"


def test_position_service_modifies_paper_buy_tp_and_percent() -> None:
    db = _session()
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="PAPER",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.04,
        open_price=100.0,
        current_price=100.0,
        sl=None,
        tp=100.09,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=None,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    ok, message, updated = PositionService(db).modify_take_profit(position.id, 101.0)

    assert ok is True
    assert message == "Paper TP updated"
    assert updated is not None
    assert updated.tp == 101.0
    assert round(updated.tp_percent or 0, 2) == 1.0


def test_position_service_rejects_buy_tp_below_entry() -> None:
    db = _session()
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="PAPER",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.04,
        open_price=100.0,
        current_price=100.0,
        sl=None,
        tp=None,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=None,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    ok, message, _ = PositionService(db).modify_take_profit(position.id, 99.0)

    assert ok is False
    assert "above entry" in message


def test_mt5_position_sync_closes_missing_ticket() -> None:
    db = _session()
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        volume=0.04,
        open_price=100.0,
        current_price=100.0,
        sl=None,
        tp=101.0,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=789,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    result = PositionService(db).sync_mt5_positions(
        positions=[],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    assert result["closed"] == 1
    assert db.get(Position, position.id).status == "CLOSED"


def test_mt5_position_sync_closes_missing_ticket_with_unknown_local_account() -> None:
    db = _session()
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUEUR",
        broker_symbol="XAUEUR",
        mode="DEMO",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.03,
        open_price=100.0,
        current_price=100.0,
        sl=None,
        tp=101.0,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=987,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    result = PositionService(db).sync_mt5_positions(
        positions=[],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    assert result["closed"] == 1
    assert db.get(Position, position.id).status == "CLOSED"


def test_mt5_position_sync_uses_history_deal_for_closed_position() -> None:
    db = _session()
    closed_time = datetime(2026, 4, 27, 12, 30, tzinfo=UTC)
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        volume=0.04,
        open_price=100.0,
        current_price=100.0,
        sl=None,
        tp=101.0,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=789,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    result = PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[
            {
                "position_id": 789,
                "ticket": 555,
                "time_msc": int(closed_time.timestamp() * 1000),
                "price": 99.5,
                "profit": -12.3,
                "swap": -0.4,
                "commission": -0.2,
                "raw": {"ticket": 555, "position_id": 789},
            }
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    saved = db.get(Position, position.id)
    assert result["closed"] == 1
    assert result["deals_received"] == 1
    assert saved.status == "CLOSED"
    assert saved.closed_at == closed_time
    assert saved.close_price == 99.5
    assert saved.current_price == 99.5
    assert saved.profit == -12.3
    assert saved.swap == -0.4
    assert saved.commission == -0.2
    assert saved.closing_deal_ticket == 555
    assert saved.close_payload_json == {"ticket": 555, "position_id": 789}


def test_mt5_position_sync_sums_position_deals_for_closed_profit() -> None:
    db = _session()
    closed_time = datetime(2026, 4, 28, 12, 30, tzinfo=UTC)
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        volume=0.04,
        open_price=4694.16,
        current_price=4694.16,
        sl=None,
        tp=4698.39,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=790,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    result = PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[
            {
                "position_id": 790,
                "ticket": 601,
                "entry": 0,
                "time_msc": int((closed_time.timestamp() - 60) * 1000),
                "price": 4694.16,
                "volume": 0.04,
                "profit": 0.0,
                "swap": 0.0,
                "commission": 0.0,
            },
            {
                "position_id": 790,
                "ticket": 602,
                "entry": 1,
                "time_msc": int(closed_time.timestamp() * 1000),
                "price": 4694.56,
                "volume": 0.04,
                "profit": 1.59,
                "swap": -0.1,
                "commission": -0.2,
            },
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    saved = db.get(Position, position.id)
    assert result["closed"] == 1
    assert result["deals_received"] == 2
    assert saved.status == "CLOSED"
    assert saved.closed_at == closed_time
    assert saved.close_price == pytest.approx(4694.56)
    assert saved.profit == pytest.approx(1.59)
    assert saved.swap == pytest.approx(-0.1)
    assert saved.commission == pytest.approx(-0.2)
    assert saved.closing_deal_ticket == 602


def test_trade_history_endpoint_lists_closed_positions() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="PAPER",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.04,
        open_price=100.0,
        current_price=101.0,
        sl=None,
        tp=101.0,
        profit=1.0,
        status="CLOSED",
        mt5_position_ticket=None,
        magic_number=260426,
        opened_at=datetime.now(UTC),
        closed_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()
    app = FastAPI()
    app.include_router(trade_history_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/api/trade-history?symbol=XAUUSD&status=CLOSED")

    assert response.status_code == 200
    assert response.json()[0]["position_id"] == position.id

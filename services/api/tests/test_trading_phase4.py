from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
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
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
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
    return SimpleNamespace(internal_symbol="XAUUSD", broker_symbol="XAUUSDm", enabled=enabled)


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
            broker_symbol="XAUUSDm",
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
            broker_symbol="XAUUSDm",
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

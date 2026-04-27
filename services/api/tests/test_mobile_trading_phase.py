from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.trading.lot_sizing import calculate_buy_take_profit, calculate_lot_size
from app.trading.routes import router as trading_router
from app.trading.schemas import ManualOrderRequest
from app.users.models import User, UserRole


def _settings(**overrides: object) -> SimpleNamespace:
    defaults = {
        "trading_mode": "PAPER",
        "live_trading_enabled": False,
        "require_live_confirmation": True,
        "max_order_volume": None,
        "allow_market_orders": True,
        "allow_pending_orders": False,
        "is_paused": False,
        "long_only": True,
        "default_take_profit_percent": 0.09,
        "use_stop_loss": False,
        "mt5_order_execution_enabled": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _symbol() -> SimpleNamespace:
    return SimpleNamespace(
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        enabled=True,
        tradable=True,
        analysis_only=False,
    )


def _tick() -> SimpleNamespace:
    return SimpleNamespace(time=datetime.now(UTC), bid=4716.45, ask=4716.62, last=None)


def _mt5_status() -> SimpleNamespace:
    return SimpleNamespace(connected_to_mt5=False, account_trade_mode="UNKNOWN", updated_at=datetime.now(UTC))


class DummyRiskManager(RiskManager):
    def __init__(self, tick: SimpleNamespace | None) -> None:
        self._tick = tick

    def latest_tick(self, internal_symbol: str) -> SimpleNamespace | None:
        return self._tick

    def _apply_news_zone_rules(self, internal_symbol: str, reasons: list[str], warnings: list[str]) -> None:
        return None


def test_lot_size_uses_equity_rule_and_multiplier() -> None:
    base = calculate_lot_size(available_equity=10000, equity_per_0_01_lot=2500, minimum_lot=0.01)
    doubled = calculate_lot_size(available_equity=10000, equity_per_0_01_lot=2500, minimum_lot=0.01, multiplier=2)
    tripled = calculate_lot_size(available_equity=10000, equity_per_0_01_lot=2500, minimum_lot=0.01, multiplier=3)

    assert base.base_lot == 0.04
    assert doubled.effective_lot == 0.08
    assert tripled.effective_lot == 0.12


def test_lot_size_large_equity_examples_and_min_multiplier() -> None:
    base = calculate_lot_size(available_equity=50000, equity_per_0_01_lot=2500, minimum_lot=0.01)
    doubled = calculate_lot_size(available_equity=50000, equity_per_0_01_lot=2500, minimum_lot=0.01, multiplier=2)
    tripled = calculate_lot_size(available_equity=50000, equity_per_0_01_lot=2500, minimum_lot=0.01, multiplier=3)
    clamped = calculate_lot_size(available_equity=50000, equity_per_0_01_lot=2500, minimum_lot=0.01, multiplier=0)

    assert base.base_lot == 0.2
    assert doubled.effective_lot == 0.4
    assert tripled.effective_lot == 0.6
    assert clamped.multiplier == 1
    assert clamped.effective_lot == 0.2


def test_take_profit_percent_calculation() -> None:
    assert calculate_buy_take_profit(4716.62, 0.09) == pytest.approx(4720.864958)


def test_risk_manager_blocks_sell_when_long_only_enabled() -> None:
    decision = DummyRiskManager(_tick()).evaluate(
        order=ManualOrderRequest(internal_symbol="XAUUSD", side="SELL", volume=0.01),
        trading_settings=_settings(long_only=True),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status(),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "SELL orders are disabled because long_only is enabled" in decision.reasons


def test_risk_manager_blocks_stop_loss_when_disabled() -> None:
    decision = DummyRiskManager(_tick()).evaluate(
        order=ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01, sl=4700.0),
        trading_settings=_settings(use_stop_loss=False),
        symbol_mapping=_symbol(),
        mt5_status=_mt5_status(),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "Stop loss is disabled by trading settings" in decision.reasons


def test_risk_manager_blocks_demo_when_mt5_execution_disabled() -> None:
    decision = DummyRiskManager(_tick()).evaluate(
        order=ManualOrderRequest(
            internal_symbol="XAUUSD",
            side="BUY",
            volume=0.01,
            client_confirmation={"confirmed": True, "mode_acknowledged": "DEMO"},
        ),
        trading_settings=_settings(trading_mode="DEMO", mt5_order_execution_enabled=False),
        symbol_mapping=_symbol(),
        mt5_status=SimpleNamespace(connected_to_mt5=True, account_trade_mode="DEMO", updated_at=datetime.now(UTC)),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "MT5 order execution is disabled in Torum settings" in decision.reasons


def test_lot_size_endpoint_returns_minimum_without_account_equity() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = session_local()
    user = User(id=1, username="admin", email="admin@example.com", hashed_password="test", role=UserRole.admin, is_active=True)
    db.add(user)
    db.add(
        TradingSettings(
            user_id=None,
            trading_mode="PAPER",
            live_trading_enabled=False,
            require_live_confirmation=True,
            default_volume=0.01,
            default_magic_number=260426,
            default_deviation_points=20,
            allow_market_orders=True,
            allow_pending_orders=False,
            long_only=True,
            default_take_profit_percent=0.09,
            use_stop_loss=False,
            lot_per_equity_enabled=True,
            equity_per_0_01_lot=2500,
            minimum_lot=0.01,
            allow_manual_lot_adjustment=True,
            show_bid_line=True,
            show_ask_line=True,
            mt5_order_execution_enabled=False,
        )
    )
    db.commit()

    app = FastAPI()
    app.include_router(trading_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/api/trading/lot-size?symbol=XAUUSD&multiplier=2")

    assert response.status_code == 200
    assert response.json()["base_lot"] == 0.01
    assert response.json()["effective_lot"] == 0.02


def test_trading_settings_endpoint_exposes_bid_ask_and_mt5_execution_flags() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = session_local()
    user = User(id=1, username="admin", email="admin@example.com", hashed_password="test", role=UserRole.admin, is_active=True)
    db.add(user)
    db.add(
        TradingSettings(
            user_id=None,
            trading_mode="PAPER",
            live_trading_enabled=False,
            require_live_confirmation=True,
            default_volume=0.01,
            default_magic_number=260426,
            default_deviation_points=20,
            allow_market_orders=True,
            allow_pending_orders=False,
            long_only=True,
            default_take_profit_percent=0.09,
            use_stop_loss=False,
            lot_per_equity_enabled=True,
            equity_per_0_01_lot=2500,
            minimum_lot=0.01,
            allow_manual_lot_adjustment=True,
            show_bid_line=True,
            show_ask_line=True,
            mt5_order_execution_enabled=False,
        )
    )
    db.commit()

    app = FastAPI()
    app.include_router(trading_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/api/trading/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["show_bid_line"] is True
    assert payload["show_ask_line"] is True
    assert payload["mt5_order_execution_enabled"] is False

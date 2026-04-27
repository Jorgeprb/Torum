from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.market_data.diagnostics import latest_tick_for_symbol, latest_tick_to_read
from app.mt5.schemas import MT5StatusPayload
from app.mt5.status_store import mt5_status_store
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.ticks.router import router as ticks_router
from app.users.models import User  # noqa: F401


def _client_with_db() -> tuple[TestClient, object]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = session_local()
    app = FastAPI()
    app.include_router(ticks_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db


def test_latest_tick_read_returns_latest_bid_ask_and_age() -> None:
    _, db = _client_with_db()
    old_time = datetime.now(UTC) - timedelta(seconds=10)
    new_time = datetime.now(UTC)
    db.add_all(
        [
            Tick(id=1, time=old_time, internal_symbol="XAUUSD", broker_symbol="XAUUSD", bid=4700.0, ask=4700.2, last=None, volume=0, source="MT5"),
            Tick(id=2, time=new_time, internal_symbol="XAUUSD", broker_symbol="XAUUSD", bid=4705.6, ask=4705.82, last=None, volume=0, source="MT5"),
        ]
    )
    db.commit()

    tick = latest_tick_for_symbol(db, "XAUUSD")
    assert tick is not None
    payload = latest_tick_to_read(tick)

    assert payload.bid == 4705.6
    assert payload.ask == 4705.82
    assert payload.symbol == "XAUUSD"
    assert payload.mid == 4705.71
    assert payload.spread == pytest.approx(0.22)
    assert payload.source == "MT5"


def test_tick_batch_ignores_mock_when_market_source_is_mt5_and_mt5_connected() -> None:
    client, db = _client_with_db()
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
            allow_market_orders=True,
            allow_pending_orders=False,
            market_data_source="MT5",
        )
    )
    db.commit()
    mt5_status_store.update(MT5StatusPayload(connected_to_mt5=True, account_trade_mode="DEMO"))

    response = client.post(
        "/api/ticks/batch",
        json={
            "source": "MOCK",
            "ticks": [
                {
                    "internal_symbol": "XAUUSD",
                    "broker_symbol": "XAUUSD",
                    "time": "2026-04-27T12:00:00Z",
                    "bid": 9999.0,
                    "ask": 9999.2,
                    "volume": 0,
                }
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["inserted"] == 0
    assert payload["source"] == "MOCK"
    assert payload["errors"] == ["MOCK ticks ignored because market_data_source=MT5"]
    assert db.query(Tick).count() == 0
    mt5_status_store.update(MT5StatusPayload())

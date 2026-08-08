from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.candles.models import Candle
from app.db.base import Base
from app.db.session import get_db
from app.orders.models import Order
from app.orders.router import router as orders_router
from app.orders.service import OrderManager
from app.positions.models import Position
from app.positions.router import router as positions_router
from app.positions.service import PositionService, _mt5_comments_match
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.strategies.models import StrategyConfig, StrategySignal
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trade_history.routes import router as trade_history_router
from app.trade_jobs.models import TradeJob
from app.trade_jobs.service import _dispatch_job
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
        ManualOrderRequest(
            internal_symbol="XAUUSD",
            side="BUY",
            volume=0.01,
            client_confirmation={"confirmed": True, "risk_acknowledged": True},
        ),
        user,
    )

    assert response.ok is True
    assert response.status == "EXECUTED"
    assert db.query(Order).count() == 1
    assert db.query(Position).count() == 1


def test_strategy_order_sends_push_when_bot_buys(monkeypatch) -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    sent: list[dict[str, object]] = []

    def fake_send(self, user_id: int, **payload):  # type: ignore[no-untyped-def]
        sent.append({"user_id": user_id, **payload})
        return 1, 0

    monkeypatch.setattr("app.alerts.push.PushNotificationService.send_bot_order_executed", fake_send)

    response = OrderManager(db).create_strategy_order(
        ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01),
        user,
        strategy_key="example_strategy",
        strategy_signal_id=99,
        mode="PAPER",
        strategy_settings=SimpleNamespace(strategies_enabled=True, strategy_live_enabled=True),
    )

    assert response.ok is True
    assert sent == []  # push delivery is durable and does not block order execution
    job = db.query(TradeJob).filter(TradeJob.job_type == "NOTIFY_ORDER").one()
    assert job.status == "PENDING"
    assert job.payload_json["order_id"] == response.order_id


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
        json={
            "internal_symbol": "XAUUSD",
            "side": "BUY",
            "order_type": "MARKET",
            "volume": 0.01,
            "client_confirmation": {"confirmed": True, "risk_acknowledged": True},
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "EXECUTED"


def test_orders_manual_endpoint_rejects_missing_risk_acknowledgement() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    app = FastAPI()
    app.include_router(orders_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).post(
        "/api/orders/manual",
        json={"internal_symbol": "XAUUSD", "side": "BUY", "order_type": "MARKET", "volume": 0.01},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "REJECTED"
    assert "risk acknowledgement" in " ".join(response.json()["reasons"]).lower()


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

    service = PositionService(db)
    result = {}
    for _ in range(3):
        result = service.sync_mt5_positions(
            positions=[],
            account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
        )

    assert result["closed"] == 1
    saved = db.get(Position, position.id)
    assert saved.status == "CLOSED"
    assert saved.sync_state == "CLOSED_BY_ABSENCE"
    assert len(saved.sync_state) <= 24


def test_mt5_position_close_survives_enrichment_queue_failure(monkeypatch) -> None:
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
        volume=0.03,
        open_price=100.0,
        current_price=101.0,
        sl=None,
        tp=101.0,
        profit=3.0,
        status="OPEN",
        mt5_position_ticket=654321,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    def fail_enqueue(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated queue failure")

    monkeypatch.setattr("app.positions.service.enqueue_trade_job", fail_enqueue)
    service = PositionService(db)
    result: dict[str, object] = {}
    for _ in range(3):
        result = service.sync_mt5_positions(
            positions=[],
            account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
        )

    saved = db.get(Position, position.id)
    assert result["closed"] == 1
    assert saved.status == "CLOSED"
    assert saved.sync_state == "CLOSED_BY_ABSENCE"
    assert saved.raw_payload_json["close_enrichment_enqueue_failed"] is True


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

    service = PositionService(db)
    result = {}
    for _ in range(3):
        result = service.sync_mt5_positions(
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
                "entry": 1,
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
    assert saved.closed_at is not None
    assert saved.closed_at.replace(tzinfo=UTC) == closed_time
    assert saved.close_price == 99.5
    assert saved.current_price == 99.5
    assert saved.profit == -12.3
    assert saved.swap == -0.4
    assert saved.commission == -0.2
    assert saved.closing_deal_ticket == 555
    assert saved.close_payload_json == {"ticket": 555, "position_id": 789}


def test_mt5_position_sync_matches_close_deal_by_persistent_identifier() -> None:
    db = _session()
    closed_time = datetime(2026, 7, 27, 12, 30, tzinfo=UTC)
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        volume=0.03,
        open_price=3592.58,
        current_price=3597.97,
        sl=None,
        tp=3595.81,
        profit=9.24,
        status="OPEN",
        mt5_position_ticket=111111,
        mt5_position_identifier=None,
        magic_number=260426,
        opened_at=datetime.now(UTC),
        raw_payload_json={"resolved_position_snapshot": {"ticket": 111111, "identifier": 222222}},
    )
    db.add(position)
    db.commit()

    result = PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[
            {
                "position_id": 222222,
                "ticket": 333333,
                "entry": 1,
                "time_msc": int(closed_time.timestamp() * 1000),
                "price": 3597.97,
                "profit": 9.24,
                "swap": -0.1,
            }
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    saved = db.get(Position, position.id)
    assert result["closed"] == 1
    assert saved.status == "CLOSED"
    assert saved.close_price == pytest.approx(3597.97)
    assert saved.closing_deal_ticket == 333333
    assert saved.sync_state == "CLOSED_CONFIRMED"


def test_manual_close_reconciles_mt5_tp_race_instead_of_returning_invalid_request() -> None:
    db = _session()
    closed_time = datetime(2026, 7, 27, 12, 30, tzinfo=UTC)
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        volume=0.03,
        open_price=3592.58,
        current_price=3597.97,
        sl=None,
        tp=3595.81,
        profit=9.24,
        status="OPEN",
        mt5_position_ticket=111111,
        mt5_position_identifier=222222,
        magic_number=260426,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    class RacingMT5Client:
        def __init__(self) -> None:
            self.position_reads = 0

        def health(self) -> dict[str, object]:
            return {"connected_to_mt5": True}

        def get_positions(self) -> list[dict[str, object]]:
            self.position_reads += 1
            if self.position_reads == 1:
                return [{"ticket": 111111, "identifier": 222222}]
            return []

        def close_position(self, ticket: int, payload: dict[str, object]) -> dict[str, object]:
            assert ticket == 111111
            return {"ok": False, "comment": "Invalid request"}

        def get_close_deal(self, ticket: int, deal: int | None = None) -> dict[str, object]:
            assert ticket == 222222
            return {
                "ok": True,
                "close_deal": {
                    "position_id": 222222,
                    "ticket": 333333,
                    "entry": 1,
                    "time_msc": int(closed_time.timestamp() * 1000),
                    "price": 3597.97,
                    "profit": 9.24,
                    "swap": -0.1,
                },
            }

    ok, message, saved = PositionService(db, mt5_client=RacingMT5Client()).close_position(position.id)

    assert ok is True
    assert "already closed" in message
    assert saved is not None
    assert saved.status == "CLOSED"
    assert saved.closed_at is not None
    assert saved.closed_at.replace(tzinfo=UTC) == closed_time
    assert saved.close_price == pytest.approx(3597.97)
    assert saved.closing_deal_ticket == 333333


def test_mt5_position_sync_links_pending_order_and_repairs_missing_tp() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    order = Order(
        user_id=user.id,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        side="BUY",
        order_type="MARKET",
        volume=0.06,
        requested_price=4515.8,
        tp=4519.89,
        status="SENT",
        magic_number=260426,
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.commit()

    class FakeMT5Client:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def modify_position_tp(self, ticket: int, payload: dict[str, object]) -> dict[str, object]:
            self.payloads.append({"ticket": ticket, **payload})
            return {"ok": True, "price": payload["tp"], "comment": "updated"}

    fake_mt5 = FakeMT5Client()

    result = PositionService(db, mt5_client=fake_mt5).sync_mt5_positions(
        positions=[
            {
                "ticket": 152093533257,
                "identifier": 152093533257,
                "symbol": "XAUUSD",
                "type": 0,
                "magic": 260426,
                "volume": 0.06,
                "price_open": 4515.83,
                "price_current": 4515.9,
                "tp": 0.0,
                "profit": 0.0,
                "time": int(datetime.now(UTC).timestamp()),
                "comment": "Torum Strategy t",
            }
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    saved_position = db.query(Position).filter(Position.mt5_position_ticket == 152093533257).one()
    saved_order = db.get(Order, order.id)
    assert result["created"] == 1
    assert saved_position.order_id == order.id
    assert saved_position.mt5_position_identifier == 152093533257
    assert saved_position.tp == pytest.approx(4519.89)
    assert saved_position.raw_payload_json["tp_status"] == "PENDING"
    assert saved_order.status == "EXECUTED"
    assert saved_order.mt5_position_ticket == 152093533257
    assert saved_order.response_payload_json["tp_status"] == "PENDING"
    assert fake_mt5.payloads == []  # APPLY_TP is executed by the durable trade-job worker
    tp_job = db.query(TradeJob).filter(TradeJob.job_type == "APPLY_TP").one()
    assert tp_job.payload_json["position_id"] == saved_position.id
    assert tp_job.payload_json["final_tp"] == pytest.approx(4519.89)


def test_mt5_position_sync_sends_push_when_tp_is_hit(monkeypatch) -> None:
    db = _session()
    closed_time = datetime(2026, 4, 27, 12, 30, tzinfo=UTC)
    sent: list[dict[str, object]] = []

    def fake_send(self, user_id: int, **payload):  # type: ignore[no-untyped-def]
        sent.append({"user_id": user_id, **payload})
        return 1, 0

    monkeypatch.setattr("app.alerts.push.PushNotificationService.send_take_profit_hit", fake_send)
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

    payload = {
        "position_id": 789,
        "ticket": 555,
        "entry": 1,
        "time_msc": int(closed_time.timestamp() * 1000),
        "price": 101.0,
        "profit": 4.0,
        "raw": {"ticket": 555, "position_id": 789},
    }
    PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[payload],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )
    PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[payload],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    assert sent == [
        {
            "user_id": 1,
            "symbol": "XAUUSD",
            "volume": 0.04,
            "close_price": 101.0,
            "profit": 4.0,
            "position_id": position.id,
        }
    ]


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


def test_mt5_sync_overwrites_provisional_open_values_and_returns_incremental_payload() -> None:
    from app.mt5.schemas import MT5AccountPayload

    db = _session()
    provisional = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=12345,
        account_server="MetaQuotes-Demo",
        side="BUY",
        volume=0.01,
        open_price=1.0,
        current_price=1.0,
        sl=None,
        tp=None,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=999,
        magic_number=260426,
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add(provisional)
    db.commit()

    official_time = 1_782_000_000
    result = PositionService(db).sync_mt5_positions(
        positions=[
            {
                "ticket": 999,
                "identifier": 999,
                "symbol": "XAUUSD",
                "side": "BUY",
                "type": 0,
                "volume": 0.01,
                "price_open": 4550.25,
                "price_current": 4551.10,
                "profit": 0.85,
                "time": official_time,
                "time_msc": official_time * 1000 + 321,
                "magic": 260426,
            }
        ],
        account=MT5AccountPayload(
            login=12345,
            server="MetaQuotes-Demo",
            trade_mode="DEMO",
            currency="EUR",
            balance=10_000,
        ),
        closed_deals=[],
    )

    db.refresh(provisional)
    assert provisional.open_price == 4550.25
    assert provisional.current_price == 4551.10
    assert provisional.open_time_msc == official_time * 1000 + 321
    assert int(provisional.opened_at.timestamp()) == official_time
    assert result["updated"] == 1
    assert result["changed_positions"][0]["id"] == provisional.id
    assert result["changed_positions"][0]["open_price"] == 4550.25


def test_mt5_deal_aggregation_uses_weighted_prices_precise_times_and_fee() -> None:
    from app.positions.service import _aggregate_position_deals

    aggregate = _aggregate_position_deals(
        [
            {
                "ticket": 1,
                "position_id": 77,
                "entry": 0,
                "volume": 0.01,
                "price": 4500.0,
                "time_msc": 1_000,
                "commission": -0.10,
            },
            {
                "ticket": 2,
                "position_id": 77,
                "entry": 0,
                "volume": 0.02,
                "price": 4515.0,
                "time_msc": 2_000,
                "commission": -0.20,
            },
            {
                "ticket": 3,
                "position_id": 77,
                "entry": 1,
                "volume": 0.03,
                "price": 4520.0,
                "time_msc": 3_456,
                "profit": 1.25,
                "swap": -0.05,
                "commission": -0.30,
                "fee": -0.02,
            },
        ]
    )

    assert aggregate["entry_price"] == pytest.approx(4510.0)
    assert aggregate["price"] == pytest.approx(4520.0)
    assert aggregate["entry_time_msc"] == 1_000
    assert aggregate["close_time_msc"] == 3_456
    assert aggregate["profit"] == pytest.approx(1.25)
    assert aggregate["swap"] == pytest.approx(-0.05)
    assert aggregate["commission"] == pytest.approx(-0.60)
    assert aggregate["fee"] == pytest.approx(-0.02)
    assert aggregate["has_entry_deal"] is True


def test_close_only_mt5_history_never_fabricates_entry_marker_data() -> None:
    from app.positions.service import _aggregate_position_deals

    aggregate = _aggregate_position_deals(
        [
            {
                "ticket": 9,
                "position_id": 77,
                "entry": 1,
                "volume": 0.09,
                "price": 4048.08,
                "time_msc": 20_000,
                "profit": 8.5,
            }
        ]
    )

    assert aggregate["has_entry_deal"] is False
    assert aggregate["entry_price"] is None
    assert aggregate["entry_time_msc"] is None
    assert aggregate["entry_time"] is None
    assert aggregate["price"] == pytest.approx(4048.08)
    assert aggregate["close_time_msc"] == 20_000


def test_close_only_mt5_history_preserves_original_entry_marker() -> None:
    from app.positions.service import _aggregate_position_deals, _apply_close_deal

    original_opened_at = datetime(2026, 7, 31, 19, 50, tzinfo=UTC)
    position = Position(
        user_id=1,
        order_id=86,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=12345,
        account_server="MetaQuotes-Demo",
        side="BUY",
        volume=0.09,
        open_price=4044.44,
        current_price=4048.08,
        sl=None,
        tp=4048.08,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=999,
        magic_number=260426,
        opened_at=original_opened_at,
        open_time_msc=20_000,
    )
    aggregate = _aggregate_position_deals(
        [
            {
                "ticket": 10,
                "position_id": 999,
                "entry": 1,
                "volume": 0.09,
                "price": 4048.08,
                "time_msc": 40_000,
                "profit": 8.5,
            }
        ]
    )

    _apply_close_deal(position, aggregate)

    assert position.open_price == pytest.approx(4044.44)
    assert position.opened_at == original_opened_at
    assert position.open_time_msc == 20_000
    assert position.close_price == pytest.approx(4048.08)
    assert position.close_time_msc == 40_000
    assert position.status == "OPEN"  # caller owns the final status transition


def _closed_m5_start(offset_bars: int = 0) -> datetime:
    now = datetime.now(UTC)
    bucket = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    return bucket - timedelta(minutes=5 * (offset_bars + 1))


def _torum_signal(db: Session, *, confirmation_time: datetime) -> StrategySignal:
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.8,
        suggested_volume=0.03,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json={
            "confirmation_candle_time": int(confirmation_time.timestamp()),
            "params": {"confirmation_ignore_doji": True},
        },
        status="SENT_TO_ORDER_MANAGER",
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def test_torum_order_revalidation_rejects_signal_after_newer_bearish_candle() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    confirmation_time = _closed_m5_start(1)
    newer_time = _closed_m5_start(0)
    db.add(
        Candle(
            time=confirmation_time, internal_symbol="XAUUSD", timeframe="M5",
            open=2320.0, high=2326.0, low=2318.0, close=2325.0, source="TEST",
        )
    )
    db.commit()
    db.add(
        Candle(
            time=newer_time, internal_symbol="XAUUSD", timeframe="M5",
            open=2325.0, high=2326.0, low=2320.0, close=2321.0, source="TEST",
        )
    )
    db.commit()
    signal = _torum_signal(db, confirmation_time=confirmation_time)

    response = OrderManager(db).create_strategy_order(
        ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.03),
        user,
        strategy_key="torum_v1",
        strategy_signal_id=signal.id,
        mode="PAPER",
        strategy_settings=SimpleNamespace(strategies_enabled=True, strategy_live_enabled=True),
    )

    assert response.ok is False
    assert response.status == "REJECTED"
    assert response.reasons == ["stale_torum_confirmation_candle"]
    assert db.query(Position).count() == 0


def test_torum_order_revalidation_accepts_latest_closed_bullish_candle() -> None:
    db = _session()
    confirmation_time = _closed_m5_start(0)
    db.add(
        Candle(
            time=confirmation_time, internal_symbol="XAUUSD", timeframe="M5",
            open=2320.0, high=2326.0, low=2318.0, close=2325.0, source="TEST",
        )
    )
    signal = _torum_signal(db, confirmation_time=confirmation_time)
    db.commit()

    allowed, reason, details = OrderManager(db)._validate_torum_confirmation(
        strategy_signal_id=signal.id,
        symbol="XAUUSD",
        checked_at=confirmation_time + timedelta(minutes=5, seconds=30),
    )

    assert allowed is True
    assert reason == "torum_confirmation_current"
    assert details["latest_closed_candle_bullish"] is True


def test_torum_order_revalidation_uses_broker_chart_clock_for_live_ticks() -> None:
    db = _session()
    real_now = datetime(2026, 7, 31, 11, 10, 30, tzinfo=UTC)
    broker_now = real_now + timedelta(hours=3)
    broker_confirmation = broker_now.replace(minute=5, second=0, microsecond=0)
    stale_utc_confirmation = real_now.replace(minute=5, second=0, microsecond=0)

    db.query(Tick).delete()
    db.add(
        Tick(
            id=2,
            time=broker_now,
            time_msc=int(broker_now.timestamp() * 1000),
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            bid=4057.0,
            ask=4057.2,
            last=None,
            volume=0.0,
            source="MT5",
        )
    )
    db.add(
        Candle(
            time=stale_utc_confirmation,
            internal_symbol="XAUUSD",
            timeframe="M5",
            open=4050.0,
            high=4058.0,
            low=4048.0,
            close=4057.0,
            source="TEST",
        )
    )
    db.commit()
    db.add(
        Candle(
            time=broker_confirmation,
            internal_symbol="XAUUSD",
            timeframe="M5",
            open=4057.0,
            high=4058.0,
            low=4050.0,
            close=4052.0,
            source="TEST",
        )
    )
    db.commit()
    stale_signal = _torum_signal(db, confirmation_time=stale_utc_confirmation)
    db.commit()

    allowed, reason, details = OrderManager(db)._validate_torum_confirmation(
        strategy_signal_id=stale_signal.id,
        symbol="XAUUSD",
        checked_at=real_now,
    )

    assert allowed is False
    assert reason == "stale_torum_confirmation_candle"
    assert details["market_clock_domain"] == "BROKER_CHART"
    assert details["checked_at"] == broker_now.isoformat()


def test_torum_order_revalidation_accepts_current_broker_chart_candle() -> None:
    db = _session()
    real_now = datetime(2026, 7, 31, 11, 10, 30, tzinfo=UTC)
    broker_now = real_now + timedelta(hours=3)
    broker_confirmation = broker_now.replace(minute=5, second=0, microsecond=0)

    db.query(Tick).delete()
    db.add(
        Tick(
            id=2,
            time=broker_now,
            time_msc=int(broker_now.timestamp() * 1000),
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            bid=4057.0,
            ask=4057.2,
            last=None,
            volume=0.0,
            source="MT5",
        )
    )
    db.add(
        Candle(
            time=broker_confirmation,
            internal_symbol="XAUUSD",
            timeframe="M5",
            open=4050.0,
            high=4058.0,
            low=4048.0,
            close=4057.0,
            source="TEST",
        )
    )
    signal = _torum_signal(db, confirmation_time=broker_confirmation)
    db.commit()

    allowed, reason, details = OrderManager(db)._validate_torum_confirmation(
        strategy_signal_id=signal.id,
        symbol="XAUUSD",
        checked_at=real_now,
    )

    assert allowed is True
    assert reason == "torum_confirmation_current"
    assert details["market_clock_domain"] == "BROKER_CHART"
    assert details["latest_closed_candle_time"] == int(broker_confirmation.timestamp())


def test_mt5_comment_reconciliation_accepts_compact_and_legacy_truncated_forms() -> None:
    assert _mt5_comments_match("Torum s123456789", "Torum s123456789") is True
    assert _mt5_comments_match("strategy-s12345678", "Torum strategy-s1234") is True
    assert _mt5_comments_match("Torum s123456789", "Torum s987654321") is False


def test_mt5_sync_reconstructs_fast_open_and_tp_when_http_response_was_lost() -> None:
    db = _session()
    confirmation_time = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=5)
    config = StrategyConfig(
        user_id=1,
        strategy_key="torum_v1",
        internal_symbol="XAUUSD",
        timeframe="M5",
        enabled=True,
        mode="DEMO",
        params_json={},
    )
    db.add(config)
    db.flush()
    signal = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=1.0,
        suggested_volume=0.09,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json={"confirmation_candle_time": int(confirmation_time.timestamp())},
        status="ORDER_RECONCILING",
    )
    db.add(signal)
    db.flush()
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        order_type="MARKET",
        volume=0.09,
        requested_price=3500.0,
        tp=3503.15,
        status="RECONCILING",
        magic_number=260426,
        comment=f"Torum s{signal.id}",
        source="STRATEGY",
        strategy_signal_id=signal.id,
        strategy_key="torum_v1",
    )
    db.add(order)
    db.flush()
    signal.order_id = order.id
    db.commit()

    opened_at = datetime.now(UTC)
    closed_at = opened_at + timedelta(seconds=2)
    result = PositionService(db).sync_mt5_positions(
        positions=[],
        closed_deals=[
            {
                "position_id": 777001,
                "ticket": 880001,
                "entry": 0,
                "type": 0,
                "time_msc": int(opened_at.timestamp() * 1000),
                "price": 3500.0,
                "volume": 0.09,
                "symbol": "XAUUSD",
                "magic": 260426,
                "comment": f"Torum s{signal.id}",
                "profit": 0.0,
                "swap": 0.0,
                "commission": 0.0,
            },
            {
                "position_id": 777001,
                "ticket": 880002,
                "entry": 1,
                "type": 1,
                "time_msc": int(closed_at.timestamp() * 1000),
                "price": 3503.15,
                "volume": 0.09,
                "symbol": "XAUUSD",
                "magic": 260426,
                "comment": "tp",
                "profit": 28.35,
                "swap": 0.0,
                "commission": -0.4,
            },
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    position = db.query(Position).filter(Position.mt5_position_identifier == 777001).one()
    saved_order = db.get(Order, order.id)
    saved_signal = db.get(StrategySignal, signal.id)
    saved_config = db.get(StrategyConfig, config.id)
    assert result["created"] == 1
    assert result["closed"] == 1
    assert position.status == "CLOSED"
    assert position.order_id == order.id
    assert position.volume == pytest.approx(0.09)
    assert position.open_price == pytest.approx(3500.0)
    assert position.close_price == pytest.approx(3503.15)
    assert position.profit == pytest.approx(28.35)
    assert position.closing_deal_ticket == 880002
    assert saved_order is not None and saved_order.status == "EXECUTED"
    assert saved_order.mt5_position_ticket == 777001
    assert saved_signal is not None and saved_signal.status == "ORDER_EXECUTED"
    assert saved_config is not None
    assert int(confirmation_time.timestamp()) in saved_config.params_json["executed_entry_cycle_boundaries"]


def test_torum_order_revalidation_rejects_late_entry_inside_same_following_m5() -> None:
    db = _session()
    confirmation_time = _closed_m5_start(0)
    db.add(
        Candle(
            time=confirmation_time, internal_symbol="XAUUSD", timeframe="M5",
            open=2320.0, high=2326.0, low=2318.0, close=2325.0, source="TEST",
        )
    )
    signal = _torum_signal(db, confirmation_time=confirmation_time)
    db.commit()

    allowed, reason, details = OrderManager(db)._validate_torum_confirmation(
        strategy_signal_id=signal.id,
        symbol="XAUUSD",
        checked_at=confirmation_time + timedelta(minutes=6, seconds=1),
    )

    assert allowed is False
    assert reason == "stale_torum_confirmation_candle"
    assert details["confirmation_age_seconds"] == 61.0


def _live_order_for_mt5_execution_test(db: Session, *, volume: float = 0.03) -> Order:
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        order_type="MARKET",
        volume=volume,
        requested_price=3500.0,
        tp=3503.15,
        status="VALIDATING",
        magic_number=260426,
        comment="Torum s999",
        source="STRATEGY",
        strategy_key="torum_v1",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_api_mt5_execution_uses_authoritative_partial_fill_volume() -> None:
    db = _session()
    order = _live_order_for_mt5_execution_test(db, volume=0.03)

    class FakeMT5Client:
        def execute_market_order(self, payload):  # type: ignore[no-untyped-def]
            return {
                "ok": True,
                "retcode": 10010,
                "comment": "done partial",
                "order": 5001,
                "deal": 5002,
                "position": 5003,
                "price": 3500.1,
                "volume": 0.01,
                "raw": {},
            }

    response = OrderManager(db, mt5_client=FakeMT5Client())._execute_mt5(  # type: ignore[arg-type]
        order,
        ManualOrderRequest(
            internal_symbol="XAUUSD",
            side="BUY",
            volume=0.03,
            tp_percent=0.09,
            comment="Torum s999",
        ),
        [],
        260426,
        20,
    )

    position = db.query(Position).filter(Position.order_id == order.id).one()
    assert response.ok is True
    assert response.status == "EXECUTED"
    assert "mt5_partial_fill" in response.warnings
    assert db.get(Order, order.id).volume == pytest.approx(0.01)
    assert position.volume == pytest.approx(0.01)


def test_api_mt5_placed_without_fill_stays_reconciling_and_creates_no_position() -> None:
    db = _session()
    order = _live_order_for_mt5_execution_test(db)

    class FakeMT5Client:
        def execute_market_order(self, payload):  # type: ignore[no-untyped-def]
            return {
                "ok": True,
                "retcode": 10008,
                "comment": "placed",
                "order": 6001,
                "deal": None,
                "position": None,
                "price": 3500.1,
                "volume": 0.03,
                "raw": {},
            }

    response = OrderManager(db, mt5_client=FakeMT5Client())._execute_mt5(  # type: ignore[arg-type]
        order,
        ManualOrderRequest(
            internal_symbol="XAUUSD",
            side="BUY",
            volume=0.03,
            tp_percent=0.09,
            comment="Torum s999",
        ),
        [],
        260426,
        20,
    )

    saved_order = db.get(Order, order.id)
    assert response.ok is False
    assert response.status == "RECONCILING"
    assert saved_order is not None and saved_order.status == "RECONCILING"
    assert saved_order.response_payload_json["pending_market_fill"] is True
    assert db.query(Position).filter(Position.order_id == order.id).count() == 0


def test_mt5_sync_reconciles_partial_fill_after_lost_http_response() -> None:
    db = _session()
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=1.0,
        suggested_volume=0.09,
        reason="partial_fill_reconciliation",
        metadata_json={"confirmation_candle_time": int(datetime.now(UTC).timestamp())},
        status="ORDER_RECONCILING",
    )
    db.add(signal)
    db.flush()
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        order_type="MARKET",
        volume=0.09,
        requested_price=3500.0,
        tp=3503.15,
        status="RECONCILING",
        magic_number=260426,
        comment=f"Torum s{signal.id}",
        source="STRATEGY",
        strategy_signal_id=signal.id,
        strategy_key="torum_v1",
    )
    db.add(order)
    db.flush()
    signal.order_id = order.id
    db.commit()

    opened_at = datetime.now(UTC)
    result = PositionService(db).sync_mt5_positions(
        positions=[
            {
                "ticket": 990001,
                "identifier": 990001,
                "symbol": "XAUUSD",
                "type": 0,
                "magic": 260426,
                "volume": 0.03,
                "price_open": 3500.1,
                "price_current": 3500.2,
                "tp": 3503.15,
                "profit": 0.3,
                "time": int(opened_at.timestamp()),
                "comment": f"Torum s{signal.id}",
            }
        ],
        account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
    )

    position = db.query(Position).filter(Position.mt5_position_ticket == 990001).one()
    saved_order = db.get(Order, order.id)
    assert result["created"] == 1
    assert position.order_id == order.id
    assert position.volume == pytest.approx(0.03)
    assert saved_order is not None and saved_order.status == "EXECUTED"
    assert saved_order.mt5_position_ticket == 990001


def test_api_mt5_none_vendor_result_is_reconciled_instead_of_retried_as_new_setup() -> None:
    db = _session()
    order = _live_order_for_mt5_execution_test(db)

    class FakeMT5Client:
        def execute_market_order(self, payload):  # type: ignore[no-untyped-def]
            return {
                "ok": False,
                "retcode": None,
                "comment": "MT5 order_send returned None",
                "raw": {
                    "request": {"symbol": "XAUUSD", "volume": 0.03},
                    "last_error_code": 1,
                    "last_error_message": "terminal response unavailable",
                },
            }

    response = OrderManager(db, mt5_client=FakeMT5Client())._execute_mt5(  # type: ignore[arg-type]
        order,
        ManualOrderRequest(
            internal_symbol="XAUUSD",
            side="BUY",
            volume=0.03,
            tp_percent=0.09,
            comment="Torum s999",
        ),
        [],
        260426,
        20,
    )

    saved_order = db.get(Order, order.id)
    assert response.status == "RECONCILING"
    assert saved_order is not None and saved_order.status == "RECONCILING"
    assert saved_order.response_payload_json["ambiguous_mt5_execution"] is True
    assert db.query(Position).filter(Position.order_id == order.id).count() == 0


def test_durable_torum_strategy_job_dispatches_saved_symbols(monkeypatch) -> None:
    db = _session()
    calls: list[list[str]] = []

    def fake_run(symbols: list[str]) -> bool:
        calls.append(symbols)
        return True

    monkeypatch.setattr("app.strategies.auto_runner.run_torum_v1_for_symbols", fake_run)
    job = TradeJob(
        job_type="RUN_TORUM_STRATEGY",
        idempotency_key="run-torum:XAUUSD:1",
        status="RUNNING",
        payload_json={"symbols": ["xauusd"]},
        next_run_at=datetime.now(UTC),
    )

    _dispatch_job(db, job)

    assert calls == [["XAUUSD"]]


def test_durable_torum_strategy_job_retries_incomplete_batch(monkeypatch) -> None:
    db = _session()
    monkeypatch.setattr("app.strategies.auto_runner.run_torum_v1_for_symbols", lambda symbols: False)
    job = TradeJob(
        job_type="RUN_TORUM_STRATEGY",
        idempotency_key="run-torum:XAUUSD:2",
        status="RUNNING",
        payload_json={"symbols": ["XAUUSD"]},
        next_run_at=datetime.now(UTC),
    )

    with pytest.raises(RuntimeError, match="torum_strategy_batch_incomplete"):
        _dispatch_job(db, job)


def test_mt5_sync_releases_ambiguous_order_only_after_repeated_authoritative_absence() -> None:
    db = _session()
    signal = StrategySignal(
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=1.0,
        suggested_volume=0.09,
        reason="ambiguous_execution",
        metadata_json={"confirmation_candle_time": int(datetime.now(UTC).timestamp())},
        status="ORDER_RECONCILING",
    )
    db.add(signal)
    db.flush()
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        order_type="MARKET",
        volume=0.09,
        requested_price=3500.0,
        tp=3503.15,
        status="RECONCILING",
        magic_number=260426,
        comment=f"Torum s{signal.id}",
        source="STRATEGY",
        strategy_signal_id=signal.id,
        strategy_key="torum_v1",
        created_at=datetime.now(UTC) - timedelta(minutes=2),
        response_payload_json={"reconciliation_required": True},
    )
    db.add(order)
    db.flush()
    signal.order_id = order.id
    db.commit()
    account = SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO")

    first = PositionService(db).sync_mt5_positions(
        positions=[], account=account, closed_deals=[], deals_checked=True  # type: ignore[arg-type]
    )
    second = PositionService(db).sync_mt5_positions(
        positions=[], account=account, closed_deals=[], deals_checked=True  # type: ignore[arg-type]
    )
    assert first["reconciliation_failed"] == 0
    assert second["reconciliation_failed"] == 0
    assert db.get(Order, order.id).status == "RECONCILING"

    third = PositionService(db).sync_mt5_positions(
        positions=[], account=account, closed_deals=[], deals_checked=True  # type: ignore[arg-type]
    )

    saved_order = db.get(Order, order.id)
    saved_signal = db.get(StrategySignal, signal.id)
    assert third["reconciliation_failed"] == 1
    assert saved_order is not None and saved_order.status == "FAILED"
    assert saved_order.rejection_reason == "mt5_execution_not_found_after_authoritative_sync"
    assert saved_order.response_payload_json["reconciliation_result"] == "NOT_EXECUTED"
    assert saved_signal is not None and saved_signal.status == "ORDER_FAILED"


def test_mt5_sync_never_releases_ambiguous_order_without_complete_deal_history() -> None:
    db = _session()
    order = Order(
        user_id=1,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        account_login=123456,
        account_server="Broker-Demo",
        side="BUY",
        order_type="MARKET",
        volume=0.09,
        requested_price=3500.0,
        status="RECONCILING",
        magic_number=260426,
        comment="Torum s1",
        source="STRATEGY",
        strategy_key="torum_v1",
        created_at=datetime.now(UTC) - timedelta(hours=1),
        response_payload_json={"reconciliation_required": True},
    )
    db.add(order)
    db.commit()

    for _ in range(5):
        result = PositionService(db).sync_mt5_positions(
            positions=[],
            account=SimpleNamespace(login=123456, server="Broker-Demo", trade_mode="DEMO"),  # type: ignore[arg-type]
            closed_deals=[],
            deals_checked=False,
        )
        assert result["reconciliation_failed"] == 0

    saved = db.get(Order, order.id)
    assert saved is not None and saved.status == "RECONCILING"
    assert "reconciliation_absent_sync_count" not in (saved.response_payload_json or {})

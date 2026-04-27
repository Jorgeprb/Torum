from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.evaluator import PriceAlertEvaluator
from app.alerts.models import PriceAlert
from app.alerts.routes import router as alerts_router
from app.alerts.schemas import PriceAlertCreate
from app.alerts.service import PriceAlertService
from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.symbols.models import SymbolMapping
from app.users.models import User, UserRole


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = session_local()
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
    db.commit()
    return db


def _user(db: Session) -> User:
    user = db.get(User, 1)
    assert user is not None
    return user


def test_create_below_alert() -> None:
    db = _session()
    alert = PriceAlertService(db).create(
        PriceAlertCreate(internal_symbol="XAUUSD", timeframe="H4", target_price=4650.0),
        _user(db),
    )

    assert alert.condition_type == "BELOW"
    assert alert.status == "ACTIVE"
    assert alert.timeframe is None


def test_reject_above_alert() -> None:
    with pytest.raises(ValueError, match="Only BELOW"):
        PriceAlertCreate(internal_symbol="XAUUSD", condition_type="ABOVE", target_price=4650.0)


def test_modify_target_price_and_cancel_alert() -> None:
    db = _session()
    service = PriceAlertService(db)
    alert = service.create(PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0), _user(db))

    response = TestClient(_app(db)).patch(f"/api/alerts/price/{alert.id}", json={"target_price": 4640.0})
    assert response.status_code == 200
    assert response.json()["target_price"] == 4640.0

    response = TestClient(_app(db)).delete(f"/api/alerts/price/{alert.id}")
    assert response.status_code == 204
    assert db.get(PriceAlert, alert.id).status == "CANCELLED"


def test_evaluator_triggers_when_price_below_target_once() -> None:
    db = _session()
    alert = PriceAlertService(db).create(
        PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0),
        _user(db),
    )
    calls: list[str] = []
    evaluator = PriceAlertEvaluator(db, on_trigger=lambda event: calls.append(event.alert_id))

    events = evaluator.evaluate_symbol(symbol="XAUUSD", current_price=4649.8, checked_at=datetime.now(UTC))
    second_events = evaluator.evaluate_symbol(symbol="XAUUSD", current_price=4640.0, checked_at=datetime.now(UTC))

    assert len(events) == 1
    assert second_events == []
    assert calls == [alert.id]
    assert db.get(PriceAlert, alert.id).status == "TRIGGERED"


def test_push_service_called_when_alert_triggers() -> None:
    db = _session()
    alert = PriceAlertService(db).create(PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0), _user(db))
    push_calls: list[str] = []

    class DummyPush:
        def send_price_alert(self, event):  # type: ignore[no-untyped-def]
            push_calls.append(event.alert_id)
            return 1, 0

    PriceAlertEvaluator(db, push_service=DummyPush()).evaluate_symbol(symbol="XAUUSD", current_price=4649.8)

    assert push_calls == [alert.id]


def test_evaluator_does_not_trigger_when_price_above_target() -> None:
    db = _session()
    alert = PriceAlertService(db).create(
        PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0),
        _user(db),
    )

    events = PriceAlertEvaluator(db).evaluate_symbol(symbol="XAUUSD", current_price=4650.1, checked_at=datetime.now(UTC))

    assert events == []
    assert db.get(PriceAlert, alert.id).status == "ACTIVE"


def test_triggered_alert_not_listed_as_active() -> None:
    db = _session()
    alert = PriceAlertService(db).create(PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0), _user(db))
    PriceAlertEvaluator(db).evaluate_symbol(symbol="XAUUSD", current_price=4649.9)

    response = TestClient(_app(db)).get("/api/alerts/price?symbol=XAUUSD&status=ACTIVE")

    assert response.status_code == 200
    assert all(item["id"] != alert.id for item in response.json())


def test_tick_batch_can_drive_alert_evaluation() -> None:
    db = _session()
    alert = PriceAlertService(db).create(PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0), _user(db))
    rows = [
        {
            "internal_symbol": "XAUUSD",
            "broker_symbol": "XAUUSD",
            "time": datetime.now(UTC),
            "bid": 4649.6,
            "ask": 4650.0,
            "last": None,
            "volume": 0,
        }
    ]
    events = PriceAlertEvaluator(db).evaluate_inserted_ticks(rows)

    assert len(events) == 1
    assert db.get(PriceAlert, alert.id).status == "TRIGGERED"


def test_alert_below_uses_bid_not_mid() -> None:
    db = _session()
    alert = PriceAlertService(db).create(PriceAlertCreate(internal_symbol="XAUUSD", target_price=4650.0), _user(db))
    rows = [
        {
            "internal_symbol": "XAUUSD",
            "broker_symbol": "XAUUSD",
            "time": datetime.now(UTC),
            "bid": 4650.1,
            "ask": 4649.1,
            "last": None,
            "volume": 0,
        }
    ]

    events = PriceAlertEvaluator(db).evaluate_inserted_ticks(rows)

    assert events == []
    assert db.get(PriceAlert, alert.id).status == "ACTIVE"


def _app(db: Session) -> FastAPI:
    app = FastAPI()
    app.include_router(alerts_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _user(db)
    return app

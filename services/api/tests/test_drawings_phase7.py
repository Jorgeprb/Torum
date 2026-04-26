from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user, get_optional_current_user
from app.chart.routes import router as chart_router
from app.db.base import Base
from app.db.session import get_db
from app.drawings.models import ChartDrawing
from app.drawings.routes import router as drawings_router
from app.drawings.schemas import ChartDrawingCreate, ChartDrawingUpdate
from app.drawings.service import ChartDrawingService
from app.symbols.models import SymbolMapping
from app.users.models import User, UserRole


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
        User(
            id=2,
            username="trader",
            email="trader@example.com",
            hashed_password="test",
            role=UserRole.trader,
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
    db.commit()
    return db


def _user(db: Session, user_id: int = 1) -> User:
    user = db.get(User, user_id)
    assert user is not None
    return user


def _client(db: Session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(drawings_router, prefix="/api")
    app.include_router(chart_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user
    return TestClient(app)


def test_create_horizontal_line_valid() -> None:
    db = _session()
    client = _client(db, _user(db))

    response = client.post(
        "/api/drawings",
        json={
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "horizontal_line",
            "name": "Resistance",
            "payload": {"price": 2325.5, "label": "Resistance"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["payload"]["price"] == 2325.5
    assert db.query(ChartDrawing).count() == 1


def test_reject_invalid_horizontal_line_payload() -> None:
    db = _session()
    client = _client(db, _user(db))

    response = client.post(
        "/api/drawings",
        json={
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "horizontal_line",
            "payload": {"price": "not-a-number"},
        },
    )

    assert response.status_code == 422


def test_create_manual_zone_valid() -> None:
    payload = ChartDrawingCreate.model_validate(
        {
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "manual_zone",
            "payload": {
                "time1": 1777209600,
                "time2": None,
                "price_min": 2320.0,
                "price_max": 2335.0,
                "direction": "BUY",
                "label": "Manual buy zone",
            },
        }
    )

    assert payload.payload["direction"] == "BUY"
    assert payload.payload["price_max"] > payload.payload["price_min"]


def test_reject_manual_zone_invalid_price_range() -> None:
    db = _session()
    client = _client(db, _user(db))

    response = client.post(
        "/api/drawings",
        json={
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "manual_zone",
            "payload": {"time1": 1777209600, "price_min": 2335.0, "price_max": 2320.0},
        },
    )

    assert response.status_code == 422


def test_list_drawings_by_user_symbol_timeframe() -> None:
    db = _session()
    client = _client(db, _user(db))
    client.post(
        "/api/drawings",
        json={
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "vertical_line",
            "payload": {"time": "2026-04-26T12:00:00Z"},
        },
    )

    response = client.get("/api/drawings?symbol=XAUUSD&timeframe=H1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["payload"]["time"] == 1777204800


def test_soft_delete_hides_drawing() -> None:
    db = _session()
    client = _client(db, _user(db))
    created = client.post(
        "/api/drawings",
        json={
            "internal_symbol": "XAUUSD",
            "timeframe": "H1",
            "drawing_type": "horizontal_line",
            "payload": {"price": 2325.5},
        },
    ).json()

    response = client.delete(f"/api/drawings/{created['id']}")

    assert response.status_code == 204
    assert db.get(ChartDrawing, created["id"]).deleted_at is not None
    assert client.get("/api/drawings?symbol=XAUUSD&timeframe=H1").json() == []


def test_locked_drawing_cannot_be_edited_by_trader_but_admin_can() -> None:
    db = _session()
    trader = _user(db, 2)
    admin = _user(db, 1)
    drawing = ChartDrawing(
        user_id=trader.id,
        internal_symbol="XAUUSD",
        timeframe="H1",
        drawing_type="horizontal_line",
        payload_json={"price": 2325.5},
        style_json={},
        metadata_json={},
        locked=True,
        visible=True,
        source="MANUAL",
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)

    service = ChartDrawingService(db)
    try:
        service.update(drawing, ChartDrawingUpdate(name="Trader edit"), trader)
    except Exception as exc:
        assert "Locked drawings" in str(exc)
    else:
        raise AssertionError("Expected locked drawing update to fail")

    updated = service.update(drawing, ChartDrawingUpdate(name="Admin edit"), admin)
    assert updated.name == "Admin edit"


def test_chart_overlays_includes_visible_drawings() -> None:
    db = _session()
    user = _user(db)
    ChartDrawingService(db).create(
        ChartDrawingCreate(
            internal_symbol="XAUUSD",
            timeframe="H1",
            drawing_type="horizontal_line",
            payload={"price": 2325.5},
        ),
        user,
    )
    client = _client(db, user)

    response = client.get("/api/chart/overlays?symbol=XAUUSD&timeframe=H1")

    assert response.status_code == 200
    assert response.json()["drawings"][0]["drawing_type"] == "horizontal_line"

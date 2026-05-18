from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.candles.router import router as candles_router
from app.db.base import Base
from app.db.session import get_db


def _client_with_db() -> tuple[TestClient, Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = session_local()
    app = FastAPI()
    app.include_router(candles_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db


def _candle(time: datetime, close: float) -> Candle:
    return Candle(
        time=time,
        internal_symbol="XAUUSD",
        timeframe="M5",
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1,
        tick_count=1,
        source="TEST",
    )


def _add_candles(db: Session, candles: list[Candle]) -> None:
    for candle in candles:
        db.add(candle)
        db.flush()
    db.commit()


def test_get_candles_keeps_existing_latest_limit_order() -> None:
    client, db = _client_with_db()
    start = datetime(2026, 5, 13, 10, 0)
    _add_candles(db, [_candle(start + timedelta(minutes=5 * index), 4700 + index) for index in range(3)])

    response = client.get("/api/candles?symbol=XAUUSD&timeframe=M5&limit=2")

    assert response.status_code == 200
    assert [row["close"] for row in response.json()] == [4701, 4702]


def test_get_candles_after_returns_only_newer_candles() -> None:
    client, db = _client_with_db()
    start = datetime(2026, 5, 13, 10, 0)
    _add_candles(db, [_candle(start + timedelta(minutes=5 * index), 4700 + index) for index in range(4)])

    after = int((start.replace(tzinfo=UTC) + timedelta(minutes=5)).timestamp())
    response = client.get(f"/api/candles?symbol=XAUUSD&timeframe=M5&after={after}&limit=10")

    assert response.status_code == 200
    assert [row["time"] for row in response.json()] == [
        int((start.replace(tzinfo=UTC) + timedelta(minutes=10)).timestamp()),
        int((start.replace(tzinfo=UTC) + timedelta(minutes=15)).timestamp()),
    ]


def test_get_candles_before_returns_older_candles_ascending() -> None:
    client, db = _client_with_db()
    start = datetime(2026, 5, 13, 10, 0)
    _add_candles(db, [_candle(start + timedelta(minutes=5 * index), 4700 + index) for index in range(5)])

    before = int((start.replace(tzinfo=UTC) + timedelta(minutes=15)).timestamp())
    response = client.get(f"/api/candles?symbol=XAUUSD&timeframe=M5&before={before}&limit=2")

    assert response.status_code == 200
    assert [row["time"] for row in response.json()] == [
        int((start.replace(tzinfo=UTC) + timedelta(minutes=5)).timestamp()),
        int((start.replace(tzinfo=UTC) + timedelta(minutes=10)).timestamp()),
    ]

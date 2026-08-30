from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.mt5.models import SavedMT5Account  # noqa: F401 - register table in metadata
from app.mt5.router import router as mt5_router
from app.mt5.schemas import MT5StatusPayload
from app.mt5.status_store import mt5_status_store
from app.users.models import User, UserRole


def _client(monkeypatch) -> tuple[TestClient, Session]:  # type: ignore[no-untyped-def]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionTesting = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionTesting()
    user = User(
        username="mt5-account-user",
        email="mt5-account-user@example.com",
        hashed_password="x",
        role=UserRole.trader,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    class FakeBridgeClient:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def discover_accounts(self):  # type: ignore[no-untyped-def]
            return [
                {"login": 123456, "server": "Broker-Demo", "active": True, "source": "CURRENT"},
                {"login": 654321, "server": "Broker-Live", "active": False, "source": "TERMINAL_DATA"},
            ]

        def switch_account(self, login: int, server: str):  # type: ignore[no-untyped-def]
            return {
                "ok": True,
                "account": {
                    "login": login,
                    "server": server,
                    "name": "Saved terminal account",
                    "company": "Broker",
                    "currency": "EUR",
                    "balance": 12500.0,
                    "equity": 12480.0,
                    "margin": 100.0,
                    "margin_free": 12380.0,
                    "leverage": 100,
                    "trade_mode": "DEMO",
                },
                "generation": 1,
            }

    monkeypatch.setattr("app.mt5.router.MT5BridgeClient", FakeBridgeClient)
    mt5_status_store.update(MT5StatusPayload())

    app = FastAPI()
    app.include_router(mt5_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db


def test_saved_mt5_account_can_be_added_and_switched_without_password(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, db = _client(monkeypatch)
    try:
        created = client.post(
            "/api/mt5/accounts",
            json={"alias": "Cuenta demo", "login": 123456, "server": "Broker-Demo"},
        )
        assert created.status_code == 201
        assert created.json()["login"] == 123456
        assert "password" not in created.json()

        switched = client.post(f"/api/mt5/accounts/{created.json()['id']}/switch")
        assert switched.status_code == 200
        payload = switched.json()
        assert payload["account"]["active"] is True
        assert payload["mt5_status"]["account"]["login"] == 123456
        assert payload["mt5_status"]["account"]["server"] == "Broker-Demo"

        listed = client.get("/api/mt5/accounts")
        assert listed.status_code == 200
        assert listed.json()[0]["active"] is True
    finally:
        mt5_status_store.update(MT5StatusPayload())
        db.close()


def test_mt5_accounts_can_be_discovered_from_terminal_and_mark_saved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, db = _client(monkeypatch)
    try:
        saved = client.post(
            "/api/mt5/accounts",
            json={"login": 123456, "server": "Broker-Demo"},
        )
        assert saved.status_code == 201

        response = client.get("/api/mt5/accounts/discover")

        assert response.status_code == 200
        assert response.json() == [
            {
                "login": 123456,
                "server": "Broker-Demo",
                "active": True,
                "already_saved": True,
                "source": "CURRENT",
            },
            {
                "login": 654321,
                "server": "Broker-Live",
                "active": False,
                "already_saved": False,
                "source": "TERMINAL_DATA",
            },
        ]
    finally:
        mt5_status_store.update(MT5StatusPayload())
        db.close()


def test_saved_mt5_account_alias_accepts_unicode_and_emojis(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, db = _client(monkeypatch)
    try:
        created = client.post(
            "/api/mt5/accounts",
            json={"alias": "🚀 Oro principal 🟢", "login": 123456, "server": "Broker-Demo"},
        )
        assert created.status_code == 201
        assert created.json()["alias"] == "🚀 Oro principal 🟢"

        renamed = client.patch(
            f"/api/mt5/accounts/{created.json()['id']}",
            json={"alias": "💎 Cuenta real 🔥"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["alias"] == "💎 Cuenta real 🔥"

        listed = client.get("/api/mt5/accounts")
        assert listed.status_code == 200
        assert listed.json()[0]["alias"] == "💎 Cuenta real 🔥"
    finally:
        mt5_status_store.update(MT5StatusPayload())
        db.close()

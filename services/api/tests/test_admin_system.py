from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.admin import system as admin_system
from app.admin.system import router as admin_system_router
from app.auth.dependencies import get_current_user
from app.users.models import User, UserRole


def _app(user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_system_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_admin_status_proxies_watchdog(monkeypatch) -> None:
    user = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role=UserRole.admin, is_active=True)
    monkeypatch.setattr(
        admin_system,
        "get_settings",
        lambda: SimpleNamespace(
            watchdog_base_url="http://watchdog",
            watchdog_admin_token=SecretStr("token"),
            watchdog_timeout_seconds=2.0,
        ),
    )

    class Response:
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {"status": "OK", "items": []}

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> Response:
        assert url == "http://watchdog/status"
        assert headers["Authorization"] == "Bearer token"
        assert timeout == 2.0
        return Response()

    monkeypatch.setattr(admin_system.requests, "get", fake_get)

    response = TestClient(_app(user)).get("/api/admin/system/status")

    assert response.status_code == 200
    assert response.json()["status"] == "OK"


def test_trader_cannot_restart_watchdog() -> None:
    user = User(id=2, username="trader", email="trader@example.com", hashed_password="x", role=UserRole.trader, is_active=True)
    response = TestClient(_app(user)).post("/api/admin/system/restart/api", json={"confirmation": "REINICIAR"})

    assert response.status_code == 403


def test_restart_requires_strong_confirmation() -> None:
    user = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role=UserRole.admin, is_active=True)
    response = TestClient(_app(user)).post("/api/admin/system/restart/pc", json={"confirmation": "REINICIAR"})

    assert response.status_code == 400
    assert "REINICIAR PC" in response.json()["detail"]

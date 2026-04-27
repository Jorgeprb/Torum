from types import SimpleNamespace

from fastapi.testclient import TestClient

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.order_server import create_order_app


class FakeMT5Client:
    mt5 = None

    def is_connected(self) -> bool:
        return True

    def get_account_state(self) -> AccountState:
        return AccountState(login=123456, server="Broker-Demo", trade_mode="DEMO")  # type: ignore[arg-type]

    def initialize(self) -> None:
        return None

    def select_symbol(self, broker_symbol: str) -> bool:
        return True

    def get_latest_tick(self, broker_symbol: str) -> SimpleNamespace:
        return SimpleNamespace(bid=2325.0, ask=2325.2)


def test_order_execution_setting_can_be_changed_at_runtime() -> None:
    settings = BridgeSettings(mt5_allow_order_execution=False, mt5_allowed_account_modes="DEMO")
    client = TestClient(create_order_app(settings, FakeMT5Client()))  # type: ignore[arg-type]

    response = client.get("/settings/order-execution")
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = client.patch("/settings/order-execution", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert settings.mt5_allow_order_execution is True


def test_order_execution_setting_can_allow_demo_and_real_at_runtime() -> None:
    settings = BridgeSettings(
        mt5_allow_order_execution=False,
        mt5_allowed_account_modes="DEMO",
        mt5_enable_real_trading=False,
    )
    client = TestClient(create_order_app(settings, FakeMT5Client()))  # type: ignore[arg-type]

    response = client.patch(
        "/settings/order-execution",
        json={
            "enabled": True,
            "allowed_account_modes": ["DEMO", "REAL"],
            "enable_real_trading": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["allowed_account_modes"] == ["DEMO", "REAL"]
    assert payload["enable_real_trading"] is True
    assert settings.mt5_allowed_account_modes == "DEMO,REAL"
    assert settings.mt5_enable_real_trading is True

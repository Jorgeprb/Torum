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

    def discover_terminal_accounts(self) -> list[dict[str, object]]:
        return [
            {"login": 123456, "server": "Broker-Demo", "active": True, "source": "CURRENT"},
            {"login": 654321, "server": "Broker-Live", "active": False, "source": "TERMINAL_DATA"},
        ]

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


def test_bridge_switch_endpoint_returns_selected_account() -> None:
    settings = BridgeSettings()
    mt5_client = FakeMT5Client()
    mt5_client.account_generation = 1  # type: ignore[attr-defined]

    def switch_handler(login: int, server: str):  # type: ignore[no-untyped-def]
        previous = AccountState(login=123456, server="Broker-Demo", trade_mode="DEMO")  # type: ignore[arg-type]
        current = AccountState(login=login, server=server, trade_mode="DEMO")  # type: ignore[arg-type]
        return previous, current

    client = TestClient(create_order_app(settings, mt5_client, account_switch_handler=switch_handler))  # type: ignore[arg-type]
    response = client.post("/accounts/switch", json={"login": 654321, "server": "Broker-Other"})

    assert response.status_code == 200
    assert response.json()["account"]["login"] == 654321
    assert response.json()["account"]["server"] == "Broker-Other"


def test_bridge_discover_accounts_returns_terminal_candidates() -> None:
    settings = BridgeSettings()
    client = TestClient(create_order_app(settings, FakeMT5Client()))  # type: ignore[arg-type]

    response = client.get("/accounts/discover")

    assert response.status_code == 200
    assert response.json() == [
        {"login": 123456, "server": "Broker-Demo", "active": True, "source": "CURRENT"},
        {"login": 654321, "server": "Broker-Live", "active": False, "source": "TERMINAL_DATA"},
    ]

from pathlib import Path

from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client, MT5ClientError


class FakeMT5:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def initialize(self, *args: object, **kwargs: object) -> bool:
        self.calls.append((args, kwargs))
        return self.ok

    def last_error(self) -> tuple[int, str]:
        return (-6, "Terminal: Authorization failed")


def test_initialize_passes_explicit_terminal_login() -> None:
    mt5 = FakeMT5()
    settings = BridgeSettings(
        mt5_terminal_path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        mt5_login=123456,
        mt5_password="secret",
        mt5_server="Broker-Demo",
        mt5_timeout_ms=120000,
        mt5_portable=True,
    )

    MT5Client(settings, mt5=mt5).initialize()

    args, kwargs = mt5.calls[0]
    assert args == ("C:\\Program Files\\MetaTrader 5\\terminal64.exe",)
    assert kwargs["login"] == 123456
    assert kwargs["password"] == "secret"
    assert kwargs["server"] == "Broker-Demo"
    assert kwargs["timeout"] == 120000
    assert kwargs["portable"] is True


def test_initialize_error_keeps_mt5_last_error() -> None:
    mt5 = FakeMT5(ok=False)
    settings = BridgeSettings()

    try:
        MT5Client(settings, mt5=mt5).initialize()
    except MT5ClientError as exc:
        assert "Authorization failed" in str(exc)
    else:
        raise AssertionError("Expected MT5ClientError")


class FakeSwitchMT5(FakeMT5):
    def __init__(self) -> None:
        super().__init__()
        self.active_login = 111
        self.active_server = "Broker-Demo"
        self.login_calls: list[dict[str, object]] = []

    def account_info(self):  # type: ignore[no-untyped-def]
        trade_mode_demo = 0
        return type(
            "AccountInfo",
            (),
            {
                "login": self.active_login,
                "server": self.active_server,
                "name": "Tester",
                "company": "Broker",
                "currency": "EUR",
                "balance": 10000.0,
                "equity": 10000.0,
                "margin": 0.0,
                "margin_free": 10000.0,
                "leverage": 100,
                "trade_mode": trade_mode_demo,
            },
        )()

    def login(self, login, **kwargs):  # type: ignore[no-untyped-def]
        call = {"login": login, **kwargs}
        self.login_calls.append(call)
        self.active_login = int(login)
        self.active_server = str(kwargs["server"])
        return True


def test_switch_account_uses_terminal_saved_credentials_without_password() -> None:
    mt5 = FakeSwitchMT5()
    client = MT5Client(BridgeSettings(mt5_timeout_ms=12345), mt5=mt5)
    client.initialize()

    previous, current = client.switch_account(222, "Broker-Live")

    assert previous.login == 111
    assert current.login == 222
    assert current.server == "Broker-Live"
    assert client.account_generation == 1
    assert mt5.login_calls == [{"login": 222, "server": "Broker-Live", "timeout": 12345}]
    assert "password" not in mt5.login_calls[0]


class FakeDiscoveryMT5(FakeSwitchMT5):
    def __init__(self, data_path: Path) -> None:
        super().__init__()
        self.data_path = data_path

    def terminal_info(self):  # type: ignore[no-untyped-def]
        return type("TerminalInfo", (), {"data_path": str(self.data_path), "connected": True})()


def test_discover_terminal_accounts_uses_mt5_bases_without_reading_credentials(tmp_path: Path) -> None:
    (tmp_path / "Bases" / "Broker-Demo" / "Trades" / "111").mkdir(parents=True)
    (tmp_path / "Bases" / "Broker-Demo" / "Trades" / "222").mkdir(parents=True)
    (tmp_path / "Bases" / "Broker-Live" / "Trades" / "333").mkdir(parents=True)
    (tmp_path / "Bases" / "Default" / "Trades" / "999").mkdir(parents=True)
    (tmp_path / "Bases" / "Broker-Demo" / "Trades" / "not-an-account").mkdir(parents=True)

    mt5 = FakeDiscoveryMT5(tmp_path)
    client = MT5Client(BridgeSettings(), mt5=mt5)
    client.initialize()

    result = client.discover_terminal_accounts()

    assert result == [
        {"login": 111, "server": "Broker-Demo", "active": True, "source": "CURRENT"},
        {"login": 222, "server": "Broker-Demo", "active": False, "source": "TERMINAL_DATA"},
        {"login": 333, "server": "Broker-Live", "active": False, "source": "TERMINAL_DATA"},
    ]


def test_discover_terminal_accounts_returns_current_account_when_bases_is_missing(tmp_path: Path) -> None:
    mt5 = FakeDiscoveryMT5(tmp_path)
    client = MT5Client(BridgeSettings(), mt5=mt5)
    client.initialize()

    assert client.discover_terminal_accounts() == [
        {"login": 111, "server": "Broker-Demo", "active": True, "source": "CURRENT"}
    ]

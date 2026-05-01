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

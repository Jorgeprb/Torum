from types import SimpleNamespace

from bridge.account_state import account_state_from_mt5, detect_trade_mode


def test_detect_trade_mode_from_trade_mode_number() -> None:
    assert detect_trade_mode({"trade_mode": 0}) == "DEMO"
    assert detect_trade_mode({"trade_mode": 2}) == "REAL"


def test_detect_trade_mode_from_server_text() -> None:
    assert detect_trade_mode({"server": "ICMarketsSC-Demo"}) == "DEMO"
    assert detect_trade_mode({"server": "Broker-Live"}) == "REAL"


def test_account_state_from_mt5_object() -> None:
    state = account_state_from_mt5(
        SimpleNamespace(
            login=123,
            server="Broker-Demo",
            name="Torum",
            company="Broker",
            currency="USD",
            balance=1000.0,
            equity=1001.0,
            margin=0.0,
            margin_free=1001.0,
            leverage=100,
            trade_mode=0,
        )
    )

    assert state.login == 123
    assert state.trade_mode == "DEMO"

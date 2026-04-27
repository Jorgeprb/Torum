from types import SimpleNamespace

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.order_executor import OrderExecutor
from bridge.order_models import MarketOrderRequest


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_FOK = 2
    ORDER_FILLING_RETURN = 3
    SYMBOL_TRADE_MODE_DISABLED = 0

    def __init__(self) -> None:
        self.sent_requests: list[dict[str, object]] = []
        self.next_result: SimpleNamespace | None = None

    def symbol_info(self, broker_symbol: str) -> SimpleNamespace:
        return SimpleNamespace(
            digits=2,
            point=0.01,
            trade_mode=4,
            visible=True,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            filling_mode=self.ORDER_FILLING_IOC,
        )

    def order_send(self, request: dict[str, object]) -> SimpleNamespace | None:
        self.sent_requests.append(request)
        if self.next_result is None and getattr(self, "force_none", False):
            return None
        return SimpleNamespace(
            retcode=10009,
            comment="done",
            order=123,
            deal=456,
            position=789,
            price=request["price"],
            volume=request["volume"],
        )

    def last_error(self) -> tuple[int, str]:
        return (1, "fake mt5 error")


class FakeMT5Client:
    def __init__(self, account_mode: str = "DEMO") -> None:
        self.mt5 = FakeMT5()
        self.account_mode = account_mode

    def initialize(self) -> None:
        return None

    def get_account_state(self) -> AccountState:
        return AccountState(login=123456, server="Broker-Demo", trade_mode=self.account_mode)  # type: ignore[arg-type]

    def get_account_info(self) -> SimpleNamespace:
        return SimpleNamespace(trade_allowed=True)

    def get_terminal_info(self) -> SimpleNamespace:
        return SimpleNamespace(connected=True, trade_allowed=True, tradeapi_disabled=False)

    def is_connected(self) -> bool:
        return True

    def select_symbol(self, broker_symbol: str) -> bool:
        return broker_symbol == "XAUUSD"

    def get_latest_tick(self, broker_symbol: str) -> SimpleNamespace:
        return SimpleNamespace(bid=2325.0, ask=2325.2)


def _settings(enabled: bool) -> BridgeSettings:
    return BridgeSettings(
        mt5_allow_order_execution=enabled,
        mt5_allowed_account_modes="DEMO",
        mt5_enable_real_trading=False,
        mt5_order_comment_prefix="Torum",
    )


def _order(side: str = "BUY") -> MarketOrderRequest:
    return MarketOrderRequest(
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="DEMO",
        side=side,  # type: ignore[arg-type]
        volume=0.01,
        deviation_points=20,
        magic_number=260426,
        comment="manual",
    )


def test_order_executor_blocks_when_execution_disabled() -> None:
    client = FakeMT5Client()

    response = OrderExecutor(_settings(enabled=False), client).execute_market_order(_order())

    assert response.ok is False
    assert response.comment == "MT5 order execution is disabled"
    assert client.mt5.sent_requests == []


def test_order_executor_builds_buy_market_request_with_ask_price() -> None:
    client = FakeMT5Client()

    response = OrderExecutor(_settings(enabled=True), client).execute_market_order(_order("BUY"))

    assert response.ok is True
    assert response.order == 123
    request = client.mt5.sent_requests[0]
    assert request["type"] == client.mt5.ORDER_TYPE_BUY
    assert request["price"] == 2325.2
    assert request["symbol"] == "XAUUSD"
    assert request["magic"] == 260426
    assert request["volume"] == 0.01


def test_order_executor_logs_last_error_when_order_send_returns_none() -> None:
    client = FakeMT5Client()
    client.mt5.force_none = True

    response = OrderExecutor(_settings(enabled=True), client).execute_market_order(_order("BUY"))

    assert response.ok is False
    assert response.comment == "MT5 order_send returned None"
    assert response.raw["last_error_code"] == 1
    assert response.raw["last_error_message"] == "fake mt5 error"
    assert response.raw["request"]["symbol"] == "XAUUSD"


def test_order_executor_blocks_live_when_real_trading_disabled() -> None:
    client = FakeMT5Client(account_mode="REAL")
    settings = BridgeSettings(
        mt5_allow_order_execution=True,
        mt5_allowed_account_modes="REAL",
        mt5_enable_real_trading=False,
    )
    order = _order("BUY").model_copy(update={"mode": "LIVE"})

    response = OrderExecutor(settings, client).execute_market_order(order)

    assert response.ok is False
    assert response.comment == "Real trading is disabled in bridge config"

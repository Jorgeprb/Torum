import logging
from typing import Any

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client, MT5ClientError
from bridge.order_models import BridgeOrderResponse, ClosePositionRequest, MarketOrderRequest

logger = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, settings: BridgeSettings, mt5_client: MT5Client) -> None:
        self.settings = settings
        self.mt5_client = mt5_client

    def execute_market_order(self, payload: MarketOrderRequest) -> BridgeOrderResponse:
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if payload.order_type != "MARKET":
            return BridgeOrderResponse(ok=False, comment="Only MARKET orders are supported in Phase 4")
        if not self.mt5_client.select_symbol(payload.broker_symbol):
            return BridgeOrderResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")

        tick = self.mt5_client.get_latest_tick(payload.broker_symbol)
        if tick is None:
            return BridgeOrderResponse(ok=False, comment=f"No current tick for {payload.broker_symbol}")

        price = _tick_price_for_side(tick, payload.side)
        if price is None or price <= 0:
            return BridgeOrderResponse(ok=False, comment=f"No executable {payload.side} price for {payload.broker_symbol}")

        order_type = mt5.ORDER_TYPE_BUY if payload.side == "BUY" else mt5.ORDER_TYPE_SELL
        base_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": payload.broker_symbol,
            "volume": payload.volume,
            "type": order_type,
            "price": price,
            "sl": payload.sl or 0.0,
            "tp": payload.tp or 0.0,
            "deviation": payload.deviation_points,
            "magic": payload.magic_number,
            "comment": self._comment(payload.comment),
            "type_time": mt5.ORDER_TIME_GTC,
        }

        return self._send_with_filling_fallback(base_request, payload.volume, price)

    def close_position(self, ticket: int, payload: ClosePositionRequest) -> BridgeOrderResponse:
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if not self.mt5_client.select_symbol(payload.broker_symbol):
            return BridgeOrderResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")
        tick = self.mt5_client.get_latest_tick(payload.broker_symbol)
        if tick is None:
            return BridgeOrderResponse(ok=False, comment=f"No current tick for {payload.broker_symbol}")

        close_side = "SELL" if payload.side == "BUY" else "BUY"
        price = _tick_price_for_side(tick, close_side)
        if price is None:
            return BridgeOrderResponse(ok=False, comment=f"No close price for {payload.broker_symbol}")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": payload.broker_symbol,
            "volume": payload.volume,
            "type": mt5.ORDER_TYPE_SELL if close_side == "SELL" else mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": self.settings.mt5_default_deviation_points,
            "magic": payload.magic_number or self.settings.mt5_magic_number,
            "comment": self._comment("close"),
            "type_time": mt5.ORDER_TIME_GTC,
        }
        return self._send_with_filling_fallback(request, payload.volume, price)

    def _validate_execution_allowed(self, requested_mode: str) -> BridgeOrderResponse | None:
        if not self.settings.mt5_allow_order_execution:
            return BridgeOrderResponse(ok=False, comment="MT5 order execution is disabled")
        try:
            self.mt5_client.initialize()
            account = self.mt5_client.get_account_state()
        except MT5ClientError as exc:
            return BridgeOrderResponse(ok=False, comment=str(exc))
        if not self.mt5_client.is_connected():
            return BridgeOrderResponse(ok=False, comment="MT5 terminal is disconnected")
        if account.trade_mode not in self.settings.allowed_account_modes and account.trade_mode != "UNKNOWN":
            return BridgeOrderResponse(
                ok=False,
                comment=f"MT5 account mode {account.trade_mode} is not allowed by bridge config",
                raw={"account": account.to_payload()},
            )
        if requested_mode == "DEMO" and account.trade_mode != "DEMO":
            return BridgeOrderResponse(ok=False, comment=f"Requested DEMO but MT5 account is {account.trade_mode}")
        if requested_mode == "LIVE" and account.trade_mode != "REAL":
            return BridgeOrderResponse(ok=False, comment=f"Requested LIVE but MT5 account is {account.trade_mode}")
        if requested_mode == "LIVE" and not self.settings.mt5_enable_real_trading:
            return BridgeOrderResponse(ok=False, comment="Real trading is disabled in bridge config")
        return None

    def _send_with_filling_fallback(
        self,
        base_request: dict[str, Any],
        volume: float,
        price: float,
    ) -> BridgeOrderResponse:
        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        filling_modes = [
            getattr(mt5, "ORDER_FILLING_IOC", None),
            getattr(mt5, "ORDER_FILLING_FOK", None),
            getattr(mt5, "ORDER_FILLING_RETURN", None),
        ]
        filling_modes = [mode for mode in filling_modes if mode is not None]
        last_response: BridgeOrderResponse | None = None

        for filling_mode in filling_modes:
            request = {**base_request, "type_filling": filling_mode}
            result = mt5.order_send(request)
            response = _result_to_response(result, volume=volume, price=price)
            logger.info("MT5 order_send retcode=%s comment=%s", response.retcode, response.comment)
            if response.ok:
                return response
            last_response = response

        return last_response or BridgeOrderResponse(ok=False, comment="order_send failed without response")

    def _comment(self, comment: str | None) -> str:
        prefix = self.settings.mt5_order_comment_prefix.strip()
        suffix = (comment or "manual").strip()
        return f"{prefix} {suffix}"[:31]


def _tick_price_for_side(tick: Any, side: str) -> float | None:
    raw_price = getattr(tick, "ask", None) if side == "BUY" else getattr(tick, "bid", None)
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _result_to_response(result: Any, volume: float, price: float) -> BridgeOrderResponse:
    if result is None:
        return BridgeOrderResponse(ok=False, comment="MT5 order_send returned None")
    raw = result._asdict() if hasattr(result, "_asdict") else {
        name: getattr(result, name)
        for name in dir(result)
        if not name.startswith("_")
    }
    retcode = int(raw.get("retcode") or 0)
    ok = retcode in {10008, 10009}
    return BridgeOrderResponse(
        ok=ok,
        retcode=retcode,
        comment=str(raw.get("comment") or raw.get("retcode_external") or ""),
        order=_int_or_none(raw.get("order")),
        deal=_int_or_none(raw.get("deal")),
        position=_int_or_none(raw.get("position")),
        price=_float_or_none(raw.get("price")) or price,
        volume=_float_or_none(raw.get("volume")) or volume,
        raw=_json_safe(raw),
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

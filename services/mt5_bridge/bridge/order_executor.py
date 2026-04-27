import logging
import math
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
        symbol_info = self._get_symbol_info(payload.broker_symbol)
        if symbol_info is None:
            return BridgeOrderResponse(ok=False, comment=f"MT5 symbol_info unavailable for {payload.broker_symbol}")
        symbol_error = self._validate_symbol_can_trade(symbol_info, payload.broker_symbol)
        if symbol_error is not None:
            return symbol_error

        tick = self.mt5_client.get_latest_tick(payload.broker_symbol)
        if tick is None:
            return BridgeOrderResponse(ok=False, comment=f"No current tick for {payload.broker_symbol}")

        price = _tick_price_for_side(tick, payload.side)
        if price is None or price <= 0:
            return BridgeOrderResponse(ok=False, comment=f"No executable {payload.side} price for {payload.broker_symbol}")

        order_type = mt5.ORDER_TYPE_BUY if payload.side == "BUY" else mt5.ORDER_TYPE_SELL
        try:
            volume = self._normalize_volume(payload.volume, symbol_info)
        except MT5ClientError as exc:
            return BridgeOrderResponse(ok=False, comment=str(exc))
        price = self._normalize_price(price, symbol_info)
        sl = self._normalize_price(payload.sl, symbol_info) if payload.sl else 0.0
        tp = self._normalize_price(payload.tp, symbol_info) if payload.tp else 0.0
        base_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": payload.broker_symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": payload.deviation_points,
            "magic": payload.magic_number,
            "comment": self._comment(payload.comment),
            "type_time": mt5.ORDER_TIME_GTC,
        }

        logger.info(
            "MT5 market order prepared: symbol=%s side=%s requested_volume=%s normalized_volume=%s price=%s sl=%s tp=%s deviation=%s",
            payload.broker_symbol,
            payload.side,
            payload.volume,
            volume,
            price,
            sl,
            tp,
            payload.deviation_points,
        )
        return self._send_with_filling_fallback(
            base_request,
            volume,
            price,
            self._filling_modes_for_symbol(symbol_info),
        )

    def close_position(self, ticket: int, payload: ClosePositionRequest) -> BridgeOrderResponse:
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if not self.mt5_client.select_symbol(payload.broker_symbol):
            return BridgeOrderResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")
        symbol_info = self._get_symbol_info(payload.broker_symbol)
        if symbol_info is None:
            return BridgeOrderResponse(ok=False, comment=f"MT5 symbol_info unavailable for {payload.broker_symbol}")
        symbol_error = self._validate_symbol_can_trade(symbol_info, payload.broker_symbol)
        if symbol_error is not None:
            return symbol_error
        tick = self.mt5_client.get_latest_tick(payload.broker_symbol)
        if tick is None:
            return BridgeOrderResponse(ok=False, comment=f"No current tick for {payload.broker_symbol}")

        close_side = "SELL" if payload.side == "BUY" else "BUY"
        price = _tick_price_for_side(tick, close_side)
        if price is None:
            return BridgeOrderResponse(ok=False, comment=f"No close price for {payload.broker_symbol}")

        try:
            volume = self._normalize_volume(payload.volume, symbol_info)
        except MT5ClientError as exc:
            return BridgeOrderResponse(ok=False, comment=str(exc))
        price = self._normalize_price(price, symbol_info)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": payload.broker_symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_SELL if close_side == "SELL" else mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": self.settings.mt5_default_deviation_points,
            "magic": payload.magic_number or self.settings.mt5_magic_number,
            "comment": self._comment("close"),
            "type_time": mt5.ORDER_TIME_GTC,
        }
        return self._send_with_filling_fallback(request, volume, price, self._filling_modes_for_symbol(symbol_info))

    def _validate_execution_allowed(self, requested_mode: str) -> BridgeOrderResponse | None:
        if not self.settings.mt5_allow_order_execution:
            return BridgeOrderResponse(ok=False, comment="MT5 order execution is disabled")
        try:
            self.mt5_client.initialize()
            account = self.mt5_client.get_account_state()
            terminal_info = self.mt5_client.get_terminal_info()
        except MT5ClientError as exc:
            return BridgeOrderResponse(ok=False, comment=str(exc))
        if not self.mt5_client.is_connected():
            return BridgeOrderResponse(ok=False, comment="MT5 terminal is disconnected")
        logger.info(
            "MT5 execution precheck: connected=%s trade_allowed=%s tradeapi_disabled=%s account_mode=%s",
            getattr(terminal_info, "connected", None),
            getattr(terminal_info, "trade_allowed", None),
            getattr(terminal_info, "tradeapi_disabled", None),
            account.trade_mode,
        )
        if hasattr(terminal_info, "trade_allowed") and not bool(getattr(terminal_info, "trade_allowed")):
            logger.warning(
                "MT5 terminal reports trade_allowed=false; Torum will still call order_send so MT5 can return the real retcode/last_error."
            )
        if bool(getattr(terminal_info, "tradeapi_disabled", False)):
            logger.warning(
                "MT5 terminal reports tradeapi_disabled=true; Torum will still call order_send so MT5 can return the real retcode/last_error."
            )
        raw_account_getter = getattr(self.mt5_client, "get_account_info", None)
        if callable(raw_account_getter):
            try:
                raw_account = raw_account_getter()
            except MT5ClientError as exc:
                return BridgeOrderResponse(ok=False, comment=str(exc))
            if hasattr(raw_account, "trade_allowed") and not bool(getattr(raw_account, "trade_allowed")):
                logger.warning(
                    "MT5 account reports trade_allowed=false; Torum will still call order_send so MT5 can return the real retcode/last_error."
                )
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

    def _get_symbol_info(self, broker_symbol: str) -> Any | None:
        mt5 = self.mt5_client.mt5
        if mt5 is None or not hasattr(mt5, "symbol_info"):
            return None
        return mt5.symbol_info(broker_symbol)

    def _validate_symbol_can_trade(self, symbol_info: Any, broker_symbol: str) -> BridgeOrderResponse | None:
        mt5 = self.mt5_client.mt5
        disabled_mode = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", None) if mt5 is not None else None
        trade_mode = getattr(symbol_info, "trade_mode", None)
        logger.info(
            "MT5 symbol trade precheck: symbol=%s digits=%s point=%s trade_mode=%s visible=%s volume_min=%s volume_max=%s volume_step=%s filling_mode=%s",
            broker_symbol,
            getattr(symbol_info, "digits", None),
            getattr(symbol_info, "point", None),
            trade_mode,
            getattr(symbol_info, "visible", None),
            getattr(symbol_info, "volume_min", None),
            getattr(symbol_info, "volume_max", None),
            getattr(symbol_info, "volume_step", None),
            getattr(symbol_info, "filling_mode", None),
        )
        if disabled_mode is not None and trade_mode == disabled_mode:
            return BridgeOrderResponse(ok=False, comment=f"MT5 trading is disabled for symbol {broker_symbol}")
        return None

    def _send_with_filling_fallback(
        self,
        base_request: dict[str, Any],
        volume: float,
        price: float,
        filling_modes: list[int] | None = None,
    ) -> BridgeOrderResponse:
        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if filling_modes is None:
            filling_modes = [
                getattr(mt5, "ORDER_FILLING_IOC", None),
                getattr(mt5, "ORDER_FILLING_RETURN", None),
                getattr(mt5, "ORDER_FILLING_FOK", None),
            ]
            filling_modes = [mode for mode in filling_modes if mode is not None]
        last_response: BridgeOrderResponse | None = None

        for filling_mode in filling_modes:
            request = {**base_request, "type_filling": filling_mode}
            logger.info("MT5 order_send request: %s", _json_safe(request))
            result = mt5.order_send(request)
            response = _result_to_response(result, volume=volume, price=price, request=request, mt5=mt5)
            if result is None:
                error_code, error_message = _last_error(mt5)
                logger.error(
                    "MT5 order_send FAILED: last_error_code=%s last_error_message=%s request=%s",
                    error_code,
                    error_message,
                    _json_safe(request),
                )
            else:
                logger.info("MT5 order_send result: %s", response.raw)
                logger.info("MT5 order_send retcode=%s comment=%s", response.retcode, response.comment)
            if response.ok:
                return response
            last_response = response

        return last_response or BridgeOrderResponse(ok=False, comment="order_send failed without response")

    def _filling_modes_for_symbol(self, symbol_info: Any) -> list[int]:
        mt5 = self.mt5_client.mt5
        assert mt5 is not None
        preferred = [
            getattr(symbol_info, "filling_mode", None),
            getattr(mt5, "ORDER_FILLING_IOC", None),
            getattr(mt5, "ORDER_FILLING_RETURN", None),
            getattr(mt5, "ORDER_FILLING_FOK", None),
        ]
        modes: list[int] = []
        for mode in preferred:
            if mode is None:
                continue
            try:
                parsed = int(mode)
            except (TypeError, ValueError):
                continue
            if parsed not in modes:
                modes.append(parsed)
        return modes

    def _normalize_volume(self, requested_volume: float, symbol_info: Any) -> float:
        min_volume = _float_or_none(getattr(symbol_info, "volume_min", None)) or 0.0
        max_volume = _float_or_none(getattr(symbol_info, "volume_max", None))
        step = _float_or_none(getattr(symbol_info, "volume_step", None)) or 0.0

        volume = max(float(requested_volume), min_volume) if min_volume > 0 else float(requested_volume)
        if max_volume is not None and volume > max_volume:
            raise MT5ClientError(f"Requested volume {requested_volume} exceeds MT5 symbol max volume {max_volume}")
        if step > 0:
            volume = math.floor((volume + 1e-12) / step) * step
            if min_volume > 0 and volume < min_volume:
                volume = min_volume
            volume = round(volume, _decimal_places(step))
        return volume

    def _normalize_price(self, price: float | None, symbol_info: Any) -> float:
        if price is None:
            return 0.0
        digits = getattr(symbol_info, "digits", None)
        try:
            return round(float(price), int(digits))
        except (TypeError, ValueError):
            return float(price)

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


def _result_to_response(
    result: Any,
    volume: float,
    price: float,
    request: dict[str, Any] | None = None,
    mt5: Any | None = None,
) -> BridgeOrderResponse:
    if result is None:
        error_code, error_message = _last_error(mt5)
        return BridgeOrderResponse(
            ok=False,
            comment="MT5 order_send returned None",
            raw={
                "request": _json_safe(request or {}),
                "last_error_code": error_code,
                "last_error_message": error_message,
            },
        )
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
        raw=_json_safe({**raw, "request": request or {}}),
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


def _decimal_places(value: float) -> int:
    text = f"{value:.10f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1])


def _last_error(mt5: Any | None) -> tuple[int | None, str | None]:
    if mt5 is None or not hasattr(mt5, "last_error"):
        return None, None
    try:
        error = mt5.last_error()
    except Exception as exc:  # pragma: no cover - defensive around vendor package
        return None, str(exc)
    if isinstance(error, tuple) and len(error) >= 2:
        return _int_or_none(error[0]), str(error[1])
    if isinstance(error, list) and len(error) >= 2:
        return _int_or_none(error[0]), str(error[1])
    return None, str(error)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

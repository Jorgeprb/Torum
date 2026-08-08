import logging
import math
import re
import unicodedata
from contextlib import nullcontext
from functools import wraps
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client, MT5ClientError
from bridge.order_models import BridgeOrderResponse, ClosePositionRequest, MarketOrderRequest, ModifyPositionTpRequest, ProfitPreviewRequest, ProfitPreviewResponse

logger = logging.getLogger(__name__)

MT5_COMMENT_MAX_LEN = 20

def _serialized_order_call(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        operation = getattr(self.mt5_client, "operation", None)
        context = operation("order", func.__name__) if callable(operation) else nullcontext()
        with context:
            return func(self, *args, **kwargs)

    return wrapper


class OrderExecutor:
    def __init__(self, settings: BridgeSettings, mt5_client: MT5Client) -> None:
        self.settings = settings
        self.mt5_client = mt5_client
        self._selected_symbols: set[str] = set()
        self._symbol_info_cache: dict[str, Any] = {}
        self._filling_modes_cache: dict[str, list[int]] = {}

    @_serialized_order_call
    def execute_market_order(self, payload: MarketOrderRequest) -> BridgeOrderResponse:
        started = perf_counter()
        validate_started = perf_counter()
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error
        validate_ms = (perf_counter() - validate_started) * 1000

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if payload.order_type != "MARKET":
            return BridgeOrderResponse(ok=False, comment="Only MARKET orders are supported in Phase 4")
        select_started = perf_counter()
        if not self._select_symbol_cached(payload.broker_symbol):
            return BridgeOrderResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")
        select_ms = (perf_counter() - select_started) * 1000
        symbol_info_started = perf_counter()
        symbol_info = self._get_symbol_info(payload.broker_symbol)
        if symbol_info is None:
            return BridgeOrderResponse(ok=False, comment=f"MT5 symbol_info unavailable for {payload.broker_symbol}")
        symbol_info_ms = (perf_counter() - symbol_info_started) * 1000
        symbol_error = self._validate_symbol_can_trade(symbol_info, payload.broker_symbol)
        if symbol_error is not None:
            return symbol_error

        tick_started = perf_counter()
        tick = self.mt5_client.get_latest_tick(payload.broker_symbol)
        if tick is None:
            return BridgeOrderResponse(ok=False, comment=f"No current tick for {payload.broker_symbol}")
        tick_ms = (perf_counter() - tick_started) * 1000

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
        requested_tp = payload.tp
        if requested_tp is None and payload.tp_percent is not None:
            if payload.side == "BUY":
                requested_tp = price * (1.0 + payload.tp_percent / 100.0)
            else:
                requested_tp = price * (1.0 - payload.tp_percent / 100.0)
        tp = self._normalize_price(requested_tp, symbol_info) if requested_tp else 0.0
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

        since_time = datetime.now(UTC)
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
        send_started = perf_counter()
        response = self._send_with_filling_fallback(
            base_request,
            volume,
            price,
            self._filling_modes_for_symbol(symbol_info, payload.broker_symbol),
        )
        order_send_ms = (perf_counter() - send_started) * 1000
        if response.ok and not response.position:
            resolved_snapshot = self.resolve_position_snapshot_after_market_order(
                symbol=payload.broker_symbol,
                side=payload.side,
                volume=volume,
                magic=payload.magic_number,
                deal=response.deal,
                order=response.order,
                since_time=since_time,
            )
            if resolved_snapshot is not None:
                resolved_ticket = _int_or_none(resolved_snapshot.get("ticket") or resolved_snapshot.get("identifier"))
                response.position = resolved_ticket
                if (response.price is None or response.price <= 0) and _float_or_none(resolved_snapshot.get("price_open")):
                    response.price = _float_or_none(resolved_snapshot.get("price_open"))
                response.raw = {
                    **response.raw,
                    "resolved_position": resolved_ticket,
                    "resolved_position_snapshot": resolved_snapshot,
                    "position_resolved_by": "positions_get_recent",
                }
        logger.info(
            "order_timing_ms symbol=%s validate=%.2f select=%.2f symbol_info=%.2f tick=%.2f order_send=%.2f total=%.2f",
            payload.broker_symbol,
            validate_ms,
            select_ms,
            symbol_info_ms,
            tick_ms,
            order_send_ms,
            (perf_counter() - started) * 1000,
        )
        return response

    @_serialized_order_call
    def close_position(self, ticket: int, payload: ClosePositionRequest) -> BridgeOrderResponse:
        started = perf_counter()
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if not self._select_symbol_cached(payload.broker_symbol):
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
        response = self._send_with_filling_fallback(request, volume, price, self._filling_modes_for_symbol(symbol_info, payload.broker_symbol))
        logger.info("close_send_ms symbol=%s ticket=%s ms=%.2f", payload.broker_symbol, ticket, (perf_counter() - started) * 1000)
        if response.ok and payload.fetch_close_deal:
            lookup_started = perf_counter()
            close_deal = _load_recent_close_deal(mt5, ticket, response.deal)
            if close_deal is not None:
                response.close_deal = close_deal
                response.raw = {**response.raw, "close_deal": close_deal}
                logger.info(
                    "MT5 close deal received: ticket=%s deal=%s price=%s profit=%s swap=%s commission=%s fee=%s",
                    ticket,
                    close_deal.get("ticket") or close_deal.get("deal"),
                    close_deal.get("price"),
                    close_deal.get("profit"),
                    close_deal.get("swap"),
                    close_deal.get("commission"),
                    close_deal.get("fee"),
                )
            logger.info("close_deal_lookup_ms ticket=%s ms=%.2f", ticket, (perf_counter() - lookup_started) * 1000)
        return response

    @_serialized_order_call
    def close_deal(self, ticket: int, deal_ticket: int | None = None) -> dict[str, Any]:
        started = perf_counter()
        try:
            self.mt5_client.initialize()
        except MT5ClientError as exc:
            return {"ok": False, "comment": str(exc), "close_deal": None}
        mt5 = self.mt5_client.mt5
        if mt5 is None:
            return {"ok": False, "comment": "MT5 unavailable", "close_deal": None}
        position_deals = _load_recent_position_deals(mt5, ticket)
        close_deal = _select_recent_close_deal(position_deals, deal_ticket)
        logger.info("close_deal_lookup_ms ticket=%s deals=%s ms=%.2f", ticket, len(position_deals), (perf_counter() - started) * 1000)
        if close_deal is None:
            return {"ok": False, "comment": "close_deal_not_found", "close_deal": None, "deals": position_deals}
        return {
            "ok": True,
            "comment": "close_deal_found",
            "close_deal": close_deal,
            "deals": position_deals,
        }

    @_serialized_order_call
    def modify_position_tp(self, ticket: int, payload: ModifyPositionTpRequest) -> BridgeOrderResponse:
        validation_error = self._validate_execution_allowed(payload.mode)
        if validation_error is not None:
            return validation_error

        mt5 = self.mt5_client.mt5
        assert mt5 is not None

        if not self._select_symbol_cached(payload.broker_symbol):
            return BridgeOrderResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")
        symbol_info = self._get_symbol_info(payload.broker_symbol)
        if symbol_info is None:
            return BridgeOrderResponse(ok=False, comment=f"MT5 symbol_info unavailable for {payload.broker_symbol}")
        symbol_error = self._validate_symbol_can_trade(symbol_info, payload.broker_symbol)
        if symbol_error is not None:
            return symbol_error

        action = getattr(mt5, "TRADE_ACTION_SLTP", None)
        if action is None:
            return BridgeOrderResponse(ok=False, comment="MT5 TRADE_ACTION_SLTP is unavailable")

        tp = self._normalize_price(payload.tp, symbol_info)
        sl = self._normalize_price(payload.sl, symbol_info) if payload.sl else 0.0
        request = {
            "action": action,
            "position": ticket,
            "symbol": payload.broker_symbol,
            "sl": sl,
            "tp": tp,
            "magic": payload.magic_number or self.settings.mt5_magic_number,
            "comment": self._comment(payload.comment or "tp"),
        }
        logger.info("MT5 modify TP request prepared: symbol=%s ticket=%s tp=%s sl=%s", payload.broker_symbol, ticket, tp, sl)
        return self._send_single(request, volume=0.0, price=tp)

    @_serialized_order_call
    def calculate_profit(self, payload: ProfitPreviewRequest) -> ProfitPreviewResponse:
        try:
            self.mt5_client.initialize()
        except MT5ClientError as exc:
            return ProfitPreviewResponse(ok=False, comment=str(exc))
        mt5 = self.mt5_client.mt5
        if mt5 is None or not hasattr(mt5, "order_calc_profit"):
            return ProfitPreviewResponse(ok=False, comment="MT5 order_calc_profit unavailable")
        if not self._select_symbol_cached(payload.broker_symbol):
            return ProfitPreviewResponse(ok=False, comment=f"Symbol not available: {payload.broker_symbol}")
        order_type = mt5.ORDER_TYPE_BUY if payload.side == "BUY" else mt5.ORDER_TYPE_SELL
        try:
            profit = mt5.order_calc_profit(
                order_type,
                payload.broker_symbol,
                float(payload.volume),
                float(payload.price_open),
                float(payload.price_close),
            )
        except Exception as exc:  # pragma: no cover - vendor package defensive guard
            return ProfitPreviewResponse(ok=False, comment=str(exc))
        if profit is None:
            return ProfitPreviewResponse(ok=False, comment=str(_last_error(mt5)))
        return ProfitPreviewResponse(ok=True, profit=float(profit), comment="MT5 order_calc_profit")

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
        if broker_symbol in self._symbol_info_cache:
            return self._symbol_info_cache[broker_symbol]
        mt5 = self.mt5_client.mt5
        if mt5 is None or not hasattr(mt5, "symbol_info"):
            return None
        getter = getattr(self.mt5_client, "get_symbol_info", None)
        symbol_info = getter(broker_symbol) if callable(getter) else mt5.symbol_info(broker_symbol)
        if symbol_info is not None:
            self._symbol_info_cache[broker_symbol] = symbol_info
        return symbol_info

    def _select_symbol_cached(self, broker_symbol: str) -> bool:
        if broker_symbol in self._selected_symbols:
            return True
        selected = self.mt5_client.select_symbol(broker_symbol)
        if selected:
            self._selected_symbols.add(broker_symbol)
        return selected

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
            logger.debug("MT5 order_send request: %s", _json_safe(request))
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
                logger.debug("MT5 order_send result: %s", response.raw)
                logger.info("MT5 order_send retcode=%s comment=%s", response.retcode, response.comment)
            if response.ok:
                return response
            last_response = response
            # Filling-mode fallback is safe only when MT5 explicitly says that
            # the selected filling policy is invalid. Retrying on NO_MONEY,
            # MARKET_CLOSED or a None response adds latency and, in the worst
            # case, could duplicate an order whose local response was lost.
            if response.retcode != 10030:  # TRADE_RETCODE_INVALID_FILL
                return response

        return last_response or BridgeOrderResponse(ok=False, comment="order_send failed without response")

    def _send_single(self, request: dict[str, Any], volume: float, price: float) -> BridgeOrderResponse:
        mt5 = self.mt5_client.mt5
        assert mt5 is not None
        logger.debug("MT5 order_send request: %s", _json_safe(request))
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
            logger.debug("MT5 order_send result: %s", response.raw)
            logger.info("MT5 order_send retcode=%s comment=%s", response.retcode, response.comment)
        return response

    def _filling_modes_for_symbol(self, symbol_info: Any, broker_symbol: str | None = None) -> list[int]:
        if broker_symbol and broker_symbol in self._filling_modes_cache:
            return self._filling_modes_cache[broker_symbol]
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
        if broker_symbol:
            self._filling_modes_cache[broker_symbol] = modes
        return modes

    def resolve_position_ticket_after_market_order(
        self,
        *,
        symbol: str,
        side: str,
        volume: float,
        magic: int | None,
        deal: int | None,
        order: int | None,
        since_time: datetime,
    ) -> int | None:
        snapshot = self.resolve_position_snapshot_after_market_order(
            symbol=symbol,
            side=side,
            volume=volume,
            magic=magic,
            deal=deal,
            order=order,
            since_time=since_time,
        )
        return _int_or_none(snapshot.get("ticket") or snapshot.get("identifier")) if snapshot else None

    def resolve_position_snapshot_after_market_order(
        self,
        *,
        symbol: str,
        side: str,
        volume: float,
        magic: int | None,
        deal: int | None,
        order: int | None,
        since_time: datetime,
    ) -> dict[str, Any] | None:
        mt5 = self.mt5_client.mt5
        if mt5 is None or not hasattr(mt5, "positions_get"):
            return None
        try:
            positions = mt5.positions_get(symbol=symbol)
        except TypeError:
            positions = mt5.positions_get()
        except Exception as exc:  # pragma: no cover - defensive around vendor API
            logger.warning("positions_get_after_order_failed symbol=%s error=%s", symbol, exc)
            return None
        if not positions:
            logger.warning("position_ticket_resolve_empty symbol=%s order=%s deal=%s", symbol, order, deal)
            return None

        expected_type = _position_type_for_side(mt5, side)
        since_timestamp = int((since_time - timedelta(seconds=30)).timestamp())
        strict_candidates: list[dict[str, Any]] = []
        fallback_candidates: list[dict[str, Any]] = []
        for position in positions:
            payload = _position_to_payload(position)
            if str(payload.get("symbol") or "") != symbol:
                continue
            if magic is not None and payload.get("magic") is not None and _int_or_none(payload.get("magic")) != magic:
                continue
            if expected_type is not None and payload.get("type") is not None and _int_or_none(payload.get("type")) != expected_type:
                continue
            position_volume = _float_or_none(payload.get("volume"))
            if position_volume is not None and abs(position_volume - float(volume)) > max(0.000001, float(volume) * 0.001):
                continue
            position_identifier = _int_or_none(payload.get("identifier"))
            position_ticket = _int_or_none(payload.get("ticket"))
            if deal is not None and deal in {position_identifier, position_ticket}:
                logger.info("position_ticket_resolved_exact_deal symbol=%s deal=%s position=%s", symbol, deal, position_ticket or position_identifier)
                return payload
            fallback_candidates.append(payload)
            opened_at = _int_or_none(payload.get("time"))
            if opened_at is None or opened_at >= since_timestamp:
                strict_candidates.append(payload)

        candidates = strict_candidates or fallback_candidates
        if not candidates:
            logger.warning("position_ticket_resolve_no_match symbol=%s order=%s deal=%s", symbol, order, deal)
            return None
        ordered = sorted(candidates, key=_position_sort_key)
        snapshot = ordered[-1]
        ticket = _int_or_none(snapshot.get("ticket") or snapshot.get("identifier"))
        logger.info("position_ticket_resolved symbol=%s order=%s deal=%s position=%s", symbol, order, deal, ticket)
        return snapshot

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

    def _comment(self, comment: str | None, side: str | None = None) -> str:
        prefix = self.settings.mt5_order_comment_prefix.strip() or "Torum"

        if comment:
            normalized_comment = str(comment).strip()
            # The API may already send the complete compact Torum comment so
            # both databases retain the exact same value for reconciliation.
            raw = (
                normalized_comment
                if normalized_comment.casefold().startswith(prefix.casefold() + " ")
                else f"{prefix} {normalized_comment}"
            )
        elif side:
            raw = f"{prefix} {side}"
        else:
            raw = prefix

        safe = _sanitize_mt5_comment(raw, max_len=MT5_COMMENT_MAX_LEN)

        if not safe:
            safe = "Torum"

        return safe


def _sanitize_mt5_comment(value: str | None, max_len: int = MT5_COMMENT_MAX_LEN) -> str:
    if value is None:
        return "Torum"

    text = str(value)

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    text = re.sub(r"[^A-Za-z0-9 _.\-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "Torum"

    return text[:max_len].strip()


def _tick_price_for_side(tick: Any, side: str) -> float | None:
    raw_price = getattr(tick, "ask", None) if side == "BUY" else getattr(tick, "bid", None)
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _position_type_for_side(mt5: Any, side: str) -> int | None:
    attr = "POSITION_TYPE_BUY" if side == "BUY" else "POSITION_TYPE_SELL"
    value = getattr(mt5, attr, None)
    if value is None:
        value = 0 if side == "BUY" else 1
    return _int_or_none(value)


def _position_to_payload(position: Any) -> dict[str, Any]:
    if hasattr(position, "_asdict"):
        return position._asdict()
    return {name: getattr(position, name) for name in dir(position) if not name.startswith("_")}


def _position_sort_key(position: dict[str, Any]) -> tuple[int, int]:
    time_msc = _int_or_none(position.get("time_msc"))
    if time_msc is None:
        time_msc = (_int_or_none(position.get("time")) or 0) * 1000
    ticket = _int_or_none(position.get("ticket") or position.get("identifier")) or 0
    return time_msc, ticket


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
    ok = retcode in {10008, 10009, 10010}
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


def _load_recent_position_deals(mt5: Any, position_ticket: int) -> list[dict[str, Any]]:
    if not hasattr(mt5, "history_deals_get"):
        return []
    try:
        deals = mt5.history_deals_get(position=position_ticket)
    except TypeError:
        date_to = datetime.now(UTC) + timedelta(minutes=1)
        date_from = date_to - timedelta(days=90)
        deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        logger.warning("MT5 history_deals_get after close failed: %s", mt5.last_error() if hasattr(mt5, "last_error") else None)
        return []
    candidates = [_deal_to_payload(deal) for deal in deals if getattr(deal, "position_id", None) == position_ticket]
    candidates.sort(key=_deal_sort_key)
    return candidates


def _select_recent_close_deal(
    candidates: list[dict[str, Any]],
    deal_ticket: int | None = None,
) -> dict[str, Any] | None:
    if deal_ticket is not None:
        for deal in candidates:
            if _int_or_none(deal.get("ticket") or deal.get("deal")) == deal_ticket:
                return deal
    close_candidates = [deal for deal in candidates if _is_close_deal(deal)]
    return close_candidates[-1] if close_candidates else None


def _load_recent_close_deal(mt5: Any, position_ticket: int, deal_ticket: int | None = None) -> dict[str, Any] | None:
    return _select_recent_close_deal(_load_recent_position_deals(mt5, position_ticket), deal_ticket)


def _deal_to_payload(deal: Any) -> dict[str, Any]:
    raw = deal._asdict() if hasattr(deal, "_asdict") else {
        name: getattr(deal, name)
        for name in dir(deal)
        if not name.startswith("_")
    }
    return {
        **raw,
        "position_id": raw.get("position_id"),
        "ticket": raw.get("ticket"),
        "deal": raw.get("ticket"),
        "time": raw.get("time"),
        "time_msc": raw.get("time_msc"),
        "price": raw.get("price"),
        "volume": raw.get("volume"),
        "type": raw.get("type"),
        "fee": raw.get("fee"),
        "profit": raw.get("profit"),
        "swap": raw.get("swap"),
        "commission": raw.get("commission"),
        "symbol": raw.get("symbol"),
        "entry": raw.get("entry"),
        "raw": raw,
    }


def _is_close_deal(deal: dict[str, Any]) -> bool:
    entry = _int_or_none(deal.get("entry"))
    return entry in {1, 2, 3}


def _deal_sort_key(deal: dict[str, Any]) -> tuple[int, int]:
    time_msc = _int_or_none(deal.get("time_msc"))
    if time_msc is None:
        time_msc = (_int_or_none(deal.get("time")) or 0) * 1000
    ticket = _int_or_none(deal.get("ticket") or deal.get("deal")) or 0
    return time_msc, ticket


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

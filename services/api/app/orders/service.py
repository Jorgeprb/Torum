from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.positions.models import Position
from app.risk.manager import RiskManager
from app.settings.trading_service import get_global_trading_settings
from app.symbols.service import get_symbol_by_internal
from app.ticks.models import Tick
from app.trading.lot_sizing import calculate_buy_take_profit
from app.trading.schemas import ManualOrderRequest, ManualOrderResponse
from app.users.models import User


class OrderManager:
    def __init__(self, db: Session, mt5_client: MT5BridgeClient | None = None) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()

    def create_manual_order(self, payload: ManualOrderRequest, user: User) -> ManualOrderResponse:
        return self._create_order(payload=payload, user=user, source="MANUAL")

    def create_strategy_order(
        self,
        payload: ManualOrderRequest,
        user: User,
        *,
        strategy_key: str,
        strategy_signal_id: int,
        mode: str,
        strategy_settings: object | None = None,
    ) -> ManualOrderResponse:
        return self._create_order(
            payload=payload,
            user=user,
            source="STRATEGY",
            mode_override=mode,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            strategy_settings=strategy_settings,
        )

    def _create_order(
        self,
        *,
        payload: ManualOrderRequest,
        user: User,
        source: str,
        mode_override: str | None = None,
        strategy_key: str | None = None,
        strategy_signal_id: int | None = None,
        strategy_settings: object | None = None,
    ) -> ManualOrderResponse:
        app_settings = get_settings()
        trading_settings = get_global_trading_settings(self.db)
        risk_settings = _effective_trading_settings(trading_settings, mode_override)
        symbol_mapping = get_symbol_by_internal(self.db, payload.internal_symbol)
        mt5_status = mt5_status_store.get()
        account = mt5_status.account
        broker_symbol = symbol_mapping.broker_symbol if symbol_mapping else ""
        mode = risk_settings.trading_mode
        latest_tick = RiskManager(self.db).latest_tick(payload.internal_symbol)
        requested_price = self._side_price(payload.side, latest_tick)
        effective_tp = payload.tp
        tp_percent = payload.tp_percent or getattr(trading_settings, "default_take_profit_percent", 0.09)
        if payload.side == "BUY" and effective_tp is None and requested_price is not None:
            effective_tp = calculate_buy_take_profit(requested_price, tp_percent)
            payload.tp = effective_tp
        magic_number = payload.magic_number or trading_settings.default_magic_number
        deviation_points = payload.deviation_points or trading_settings.default_deviation_points
        request_payload = payload.model_dump(mode="json")
        request_payload.update(
            {
                "source": source,
                "strategy_key": strategy_key,
                "strategy_signal_id": strategy_signal_id,
                "calculated_tp": effective_tp,
                "tp_percent": tp_percent,
            }
        )

        order = Order(
            user_id=user.id,
            internal_symbol=payload.internal_symbol,
            broker_symbol=broker_symbol,
            mode=mode,
            account_login=account.login if account else None,
            account_server=account.server if account else None,
            side=payload.side,
            order_type=payload.order_type,
            volume=payload.volume,
            requested_price=requested_price,
            sl=payload.sl,
            tp=effective_tp,
            status="CREATED",
            magic_number=magic_number,
            comment=payload.comment,
            source=source,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            request_payload_json=request_payload,
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)

        order.status = "VALIDATING"
        risk_manager = RiskManager(self.db)
        if source == "STRATEGY":
            risk_decision = risk_manager.evaluate_strategy_order(
                order=payload,
                trading_settings=risk_settings,
                strategy_settings=strategy_settings,
                symbol_mapping=symbol_mapping,
                mt5_status=mt5_status,
                price_stale_after_seconds=app_settings.price_stale_after_seconds,
            )
        else:
            risk_decision = risk_manager.evaluate(
                order=payload,
                trading_settings=risk_settings,
                symbol_mapping=symbol_mapping,
                mt5_status=mt5_status,
                price_stale_after_seconds=app_settings.price_stale_after_seconds,
            )

        if not risk_decision.allowed:
            order.status = "REJECTED"
            order.rejection_reason = "; ".join(risk_decision.reasons)
            order.response_payload_json = {"risk": risk_decision.model_dump()}
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="REJECTED",
                mode=mode,
                message="Order rejected by risk manager",
                reasons=risk_decision.reasons,
                warnings=risk_decision.warnings,
            )

        if mode == "PAPER":
            return self._execute_paper(order, payload, latest_tick, risk_decision.warnings)

        return self._execute_mt5(
            order=order,
            payload=payload,
            warnings=risk_decision.warnings,
            magic_number=magic_number,
            deviation_points=deviation_points,
        )

    def _execute_paper(
        self,
        order: Order,
        payload: ManualOrderRequest,
        latest_tick: Tick | None,
        warnings: list[str],
    ) -> ManualOrderResponse:
        execution_price = self._side_price(payload.side, latest_tick)
        if execution_price is None:
            order.status = "REJECTED"
            order.rejection_reason = "No price available for PAPER execution"
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="REJECTED",
                mode="PAPER",
                message="No price available for PAPER execution",
                reasons=[order.rejection_reason],
                warnings=warnings,
            )

        now = datetime.now(UTC)
        order.status = "EXECUTED"
        order.executed_price = execution_price
        order.executed_at = now
        order.response_payload_json = {"ok": True, "mode": "PAPER", "price": execution_price}
        position = Position(
            user_id=order.user_id,
            order_id=order.id,
            internal_symbol=order.internal_symbol,
            broker_symbol=order.broker_symbol,
            mode=order.mode,
            account_login=order.account_login,
            account_server=order.account_server,
            side=order.side,
            volume=order.volume,
            open_price=execution_price,
            current_price=execution_price,
            sl=order.sl,
            tp=order.tp,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=None,
            magic_number=order.magic_number,
            opened_at=now,
            raw_payload_json={"source": "PAPER", "order_id": order.id},
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(order)
        return ManualOrderResponse(
            ok=True,
            order_id=order.id,
            status="EXECUTED",
            mode="PAPER",
            message="Paper order executed",
            warnings=warnings,
            reasons=[],
        )

    def _execute_mt5(
        self,
        order: Order,
        payload: ManualOrderRequest,
        warnings: list[str],
        magic_number: int,
        deviation_points: int,
    ) -> ManualOrderResponse:
        bridge_payload = {
            "internal_symbol": order.internal_symbol,
            "broker_symbol": order.broker_symbol,
            "mode": order.mode,
            "side": order.side,
            "order_type": order.order_type,
            "volume": order.volume,
            "sl": order.sl,
            "tp": order.tp,
            "deviation_points": deviation_points,
            "magic_number": magic_number,
            "comment": order.comment,
        }
        order.status = "SENT"
        self.db.commit()
        try:
            response = self.mt5_client.execute_market_order(bridge_payload)
        except MT5BridgeClientError as exc:
            order.status = "FAILED"
            order.rejection_reason = str(exc)
            order.response_payload_json = {"ok": False, "error": str(exc)}
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="FAILED",
                mode=order.mode,  # type: ignore[arg-type]
                message="MT5 bridge request failed",
                reasons=[str(exc)],
                warnings=warnings,
            )

        order.response_payload_json = response
        if not response.get("ok"):
            order.status = "FAILED"
            order.rejection_reason = str(response.get("comment") or "MT5 order rejected")
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="FAILED",
                mode=order.mode,  # type: ignore[arg-type]
                message="MT5 order rejected",
                reasons=[order.rejection_reason],
                warnings=warnings,
            )

        now = datetime.now(UTC)
        order.status = "EXECUTED"
        order.executed_at = now
        order.executed_price = _float_or_none(response.get("price"))
        order.mt5_order_ticket = _int_or_none(response.get("order"))
        order.mt5_deal_ticket = _int_or_none(response.get("deal"))
        order.mt5_position_ticket = _int_or_none(response.get("position"))
        position = Position(
            user_id=order.user_id,
            order_id=order.id,
            internal_symbol=order.internal_symbol,
            broker_symbol=order.broker_symbol,
            mode=order.mode,
            account_login=order.account_login,
            account_server=order.account_server,
            side=order.side,
            volume=order.volume,
            open_price=order.executed_price or order.requested_price or 0.0,
            current_price=order.executed_price,
            sl=order.sl,
            tp=order.tp,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=order.mt5_position_ticket,
            magic_number=order.magic_number,
            opened_at=now,
            raw_payload_json=response,
        )
        self.db.add(position)
        self.db.commit()
        return ManualOrderResponse(
            ok=True,
            order_id=order.id,
            status="EXECUTED",
            mode=order.mode,  # type: ignore[arg-type]
            message="MT5 order executed",
            warnings=warnings,
            reasons=[],
        )

    def _side_price(self, side: str, tick: Tick | None) -> float | None:
        if tick is None:
            return None
        if side == "BUY":
            return tick.ask or tick.last or tick.bid
        return tick.bid or tick.last or tick.ask


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _effective_trading_settings(trading_settings: object, mode_override: str | None) -> object:
    if mode_override is None:
        return trading_settings
    return SimpleNamespace(
        trading_mode=mode_override,
        live_trading_enabled=getattr(trading_settings, "live_trading_enabled", False),
        require_live_confirmation=getattr(trading_settings, "require_live_confirmation", True),
        default_volume=getattr(trading_settings, "default_volume", 0.01),
        default_magic_number=getattr(trading_settings, "default_magic_number", 260426),
        default_deviation_points=getattr(trading_settings, "default_deviation_points", 20),
        max_order_volume=getattr(trading_settings, "max_order_volume", None),
        allow_market_orders=getattr(trading_settings, "allow_market_orders", True),
        allow_pending_orders=getattr(trading_settings, "allow_pending_orders", False),
        is_paused=getattr(trading_settings, "is_paused", False),
        long_only=getattr(trading_settings, "long_only", True),
        default_take_profit_percent=getattr(trading_settings, "default_take_profit_percent", 0.09),
        use_stop_loss=getattr(trading_settings, "use_stop_loss", False),
        lot_per_equity_enabled=getattr(trading_settings, "lot_per_equity_enabled", True),
        equity_per_0_01_lot=getattr(trading_settings, "equity_per_0_01_lot", 2500.0),
        minimum_lot=getattr(trading_settings, "minimum_lot", 0.01),
        allow_manual_lot_adjustment=getattr(trading_settings, "allow_manual_lot_adjustment", True),
        show_bid_line=getattr(trading_settings, "show_bid_line", True),
        show_ask_line=getattr(trading_settings, "show_ask_line", True),
        mt5_order_execution_enabled=getattr(trading_settings, "mt5_order_execution_enabled", False),
        market_data_source=getattr(trading_settings, "market_data_source", "MT5"),
    )

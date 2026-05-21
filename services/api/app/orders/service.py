import logging
from datetime import UTC, datetime
from threading import Thread
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from app.alerts.push import PushNotificationService
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.positions.models import Position
from app.risk.manager import RiskManager
from app.risk.snapshot import RiskSnapshotService
from app.settings.trading_service import get_global_trading_settings
from app.symbols.service import get_symbol_by_internal
from app.ticks.models import Tick
from app.trading.lot_sizing import calculate_buy_take_profit
from app.trading.schemas import ManualOrderOrderRead, ManualOrderPositionRead, ManualOrderRequest, ManualOrderResponse
from app.users.models import User

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(
        self,
        db: Session,
        mt5_client: MT5BridgeClient | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient()
        self.background_tasks = background_tasks

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
        payload.tp_percent = tp_percent
        if payload.side == "BUY" and effective_tp is None and requested_price is not None:
            effective_tp = calculate_buy_take_profit(requested_price, tp_percent)
        logger.info(
            "Order prepared: source=%s symbol=%s side=%s requested_price=%s preliminary_tp=%s tp_percent=%s",
            source,
            payload.internal_symbol,
            payload.side,
            requested_price,
            effective_tp,
            tp_percent,
        )
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
                user_id=user.id,
                strategy_key=strategy_key,
                exclude_order_id=order.id,
                exclude_signal_id=strategy_signal_id,
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
        self.db.refresh(position)
        if self.background_tasks is None:
            self._notify_strategy_order_executed(order)
        self._schedule_post_open_tasks(order.id, position.id, final_tp=position.tp, tp_percent=payload.tp_percent)
        return ManualOrderResponse(
            ok=True,
            order_id=order.id,
            status="EXECUTED",
            mode="PAPER",
            message="Paper order executed",
            warnings=warnings,
            reasons=[],
            position=ManualOrderPositionRead.model_validate(position),
            order=ManualOrderOrderRead.model_validate(order),
            executed_price=execution_price,
            final_tp=position.tp,
            tp_status="UPDATED" if position.tp else "NONE",
            mt5_position_ticket=None,
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
            "tp": None,
            "deviation_points": deviation_points,
            "magic_number": magic_number,
            "comment": order.comment,
        }
        order.status = "SENT"
        self.db.commit()
        order_started = perf_counter()
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
        order.mt5_position_ticket = _int_or_none(
            response.get("position")
            or response.get("mt5_position_ticket")
            or (response.get("raw") or {}).get("resolved_position")
        )
        final_tp = order.tp
        if order.executed_price and payload.tp_percent:
            final_tp = _take_profit_from_executed(order.side, order.executed_price, payload.tp_percent)
        order.tp = final_tp
        tp_status = "NONE"
        if final_tp:
            if order.mt5_position_ticket:
                tp_status = "PENDING"
            else:
                tp_status = "FAILED"
                if "missing_mt5_position_ticket_for_tp" not in warnings:
                    warnings = [*warnings, "missing_mt5_position_ticket_for_tp"]
        order.response_payload_json = {
            **response,
            "tp_final": final_tp,
            "tp_status": tp_status,
            "tp_update_error": None if tp_status != "FAILED" else "missing_mt5_position_ticket_for_tp",
        }
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
            tp=final_tp,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=order.mt5_position_ticket,
            magic_number=order.magic_number,
            opened_at=now,
            raw_payload_json=order.response_payload_json,
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(order)
        self.db.refresh(position)
        logger.info(
            "api_order_total_ms symbol=%s source=%s order_id=%s ms=%.2f",
            order.internal_symbol,
            order.source,
            order.id,
            (perf_counter() - order_started) * 1000,
        )
        if self.background_tasks is None:
            self._notify_strategy_order_executed(order)
        self._schedule_post_open_tasks(order.id, position.id, final_tp=final_tp, tp_percent=payload.tp_percent)
        return ManualOrderResponse(
            ok=True,
            order_id=order.id,
            status="EXECUTED",
            mode=order.mode,  # type: ignore[arg-type]
            message="MT5 order executed",
            warnings=warnings,
            reasons=[],
            position=ManualOrderPositionRead.model_validate(position),
            order=ManualOrderOrderRead.model_validate(order),
            executed_price=order.executed_price,
            final_tp=final_tp,
            tp_status=tp_status,  # type: ignore[arg-type]
            mt5_position_ticket=order.mt5_position_ticket,
            meta={
                "api_order_total_ms": round((perf_counter() - order_started) * 1000, 2),
                "tp_status": tp_status,
            },
        )

    def _side_price(self, side: str, tick: Tick | None) -> float | None:
        if tick is None:
            return None
        if side == "BUY":
            return tick.ask or tick.last or tick.bid
        return tick.bid or tick.last or tick.ask

    def _refresh_risk_snapshot(self, symbol: str) -> None:
        try:
            RiskSnapshotService(self.db).mark_dirty(symbol)
            RiskSnapshotService(self.db).recompute(symbol)
            RiskSnapshotService(self.db).recompute(symbol, source="STRATEGY")
        except Exception:  # noqa: BLE001
            logger.exception("risk_snapshot_recompute_failed symbol=%s", symbol)

    def _schedule_post_open_tasks(
        self,
        order_id: int,
        position_id: int,
        *,
        final_tp: float | None,
        tp_percent: float | None,
    ) -> None:
        _enqueue_background_task(self.background_tasks, _post_open_tasks, order_id, position_id, final_tp, tp_percent)

    def _notify_strategy_order_executed(self, order: Order) -> None:
        if order.source != "STRATEGY" or order.user_id is None:
            return
        payload = order.response_payload_json or {}
        if payload.get("bot_order_push_sent_at"):
            return
        try:
            sent, _failed = PushNotificationService(self.db).send_bot_order_executed(
                order.user_id,
                symbol=order.internal_symbol,
                side=order.side,
                volume=float(order.volume),
                price=order.executed_price or order.requested_price,
                tp=order.tp,
                order_id=order.id,
            )
            if sent > 0:
                order.response_payload_json = {**payload, "bot_order_push_sent_at": datetime.now(UTC).isoformat()}
                self.db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("bot_order_push_failed order_id=%s", order.id)


def _enqueue_background_task(background_tasks: BackgroundTasks | None, func: Any, *args: Any) -> None:
    if background_tasks is not None:
        background_tasks.add_task(func, *args)
        return
    Thread(target=func, args=args, daemon=True).start()


def _post_open_tasks(order_id: int, position_id: int, final_tp: float | None, tp_percent: float | None) -> None:
    started = perf_counter()
    db = SessionLocal()
    try:
        order = db.get(Order, order_id)
        position = db.get(Position, position_id)
        if order is None or position is None:
            return

        payload = position.raw_payload_json or {}
        if final_tp and position.mode != "PAPER" and position.mt5_position_ticket:
            tp_started = perf_counter()
            try:
                response = MT5BridgeClient().modify_position_tp(
                    position.mt5_position_ticket,
                    {
                        "internal_symbol": position.internal_symbol,
                        "broker_symbol": position.broker_symbol,
                        "side": position.side,
                        "mode": position.mode,
                        "tp": final_tp,
                        "sl": position.sl or 0,
                        "magic_number": position.magic_number,
                        "comment": "tp-final",
                    },
                )
                if response.get("ok"):
                    confirmed_tp = _float_or_none(response.get("price")) or final_tp
                    position.tp = confirmed_tp
                    order.tp = confirmed_tp
                    payload = {**payload, "tp_status": "UPDATED", "tp_modify_response": response}
                else:
                    payload = {
                        **payload,
                        "tp_status": "FAILED",
                        "tp_update_error": str(response.get("comment") or "MT5 TP final rejected"),
                        "tp_modify_response": response,
                    }
            except MT5BridgeClientError as exc:
                payload = {**payload, "tp_status": "FAILED", "tp_update_error": str(exc)}
            logger.info("tp_background_ms position_id=%s ms=%.2f", position_id, (perf_counter() - tp_started) * 1000)
        elif final_tp and position.mode == "PAPER":
            payload = {**payload, "tp_status": "UPDATED"}
        elif final_tp:
            payload = {
                **payload,
                "tp_status": payload.get("tp_status") or "FAILED",
                "tp_update_error": payload.get("tp_update_error") or "missing_mt5_position_ticket_for_tp",
            }
        else:
            payload = {**payload, "tp_status": "NONE"}

        if tp_percent:
            payload = {**payload, "tp_percent": tp_percent}
        position.raw_payload_json = payload
        order.response_payload_json = {**(order.response_payload_json or {}), **payload}
        db.commit()

        try:
            RiskSnapshotService(db).mark_dirty(position.internal_symbol)
            RiskSnapshotService(db).recompute(position.internal_symbol)
            RiskSnapshotService(db).recompute(position.internal_symbol, source="STRATEGY")
        except Exception:  # noqa: BLE001
            logger.exception("risk_snapshot_recompute_failed symbol=%s", position.internal_symbol)

        if order.source == "STRATEGY" and order.user_id is not None and not (order.response_payload_json or {}).get("bot_order_push_sent_at"):
            try:
                sent, _failed = PushNotificationService(db).send_bot_order_executed(
                    order.user_id,
                    symbol=order.internal_symbol,
                    side=order.side,
                    volume=float(order.volume),
                    price=order.executed_price or order.requested_price,
                    tp=order.tp,
                    order_id=order.id,
                )
                if sent > 0:
                    order.response_payload_json = {
                        **(order.response_payload_json or {}),
                        "bot_order_push_sent_at": datetime.now(UTC).isoformat(),
                    }
            except Exception:  # noqa: BLE001
                logger.exception("bot_order_push_failed order_id=%s", order.id)
        db.commit()
        logger.info("post_open_tasks_ms order_id=%s position_id=%s ms=%.2f", order_id, position_id, (perf_counter() - started) * 1000)
    finally:
        db.close()


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


def _take_profit_from_executed(side: str, executed_price: float, tp_percent: float) -> float | None:
    if executed_price <= 0 or tp_percent <= 0:
        return None
    if side == "BUY":
        return calculate_buy_take_profit(executed_price, tp_percent)
    return round(executed_price * (1 - tp_percent / 100), 8)


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

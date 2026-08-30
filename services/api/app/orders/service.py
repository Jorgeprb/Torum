import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from app.alerts.push import PushNotificationService
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.decision_log import trace_event, trace_exception
from app.candles.models import Candle
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.status_store import mt5_status_store
from app.market_data.chart_clock import resolve_market_clock
from app.orders.models import Order
from app.positions.models import Position
from app.risk.manager import RiskManager
from app.risk.schemas import RiskDecision
from app.risk.snapshot import RiskSnapshotService
from app.trade_jobs.service import enqueue_trade_job
from app.settings.trading_service import get_global_trading_settings
from app.strategies.models import StrategySignal
from app.symbols.service import get_symbol_by_internal
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by
from app.trading.lot_sizing import calculate_buy_take_profit
from app.trading.schemas import ManualOrderOrderRead, ManualOrderPositionRead, ManualOrderRequest, ManualOrderResponse
from app.users.models import User
from app.websockets.manager import market_ws_manager

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(
        self,
        db: Session,
        mt5_client: MT5BridgeClient | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        self.db = db
        self.mt5_client = mt5_client or MT5BridgeClient(
            timeout=max(0.25, float(get_settings().mt5_order_request_timeout_seconds))
        )
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
        prevalidated_risk_decision: RiskDecision | None = None,
        latest_tick_override: Tick | None = None,
    ) -> ManualOrderResponse:
        return self._create_order(
            payload=payload,
            user=user,
            source="STRATEGY",
            mode_override=mode,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            strategy_settings=strategy_settings,
            prevalidated_risk_decision=prevalidated_risk_decision,
            latest_tick_override=latest_tick_override,
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
        prevalidated_risk_decision: RiskDecision | None = None,
        latest_tick_override: Tick | None = None,
    ) -> ManualOrderResponse:
        app_settings = get_settings()
        trading_settings = get_global_trading_settings(self.db)
        risk_settings = _effective_trading_settings(trading_settings, mode_override)
        symbol_mapping = get_symbol_by_internal(self.db, payload.internal_symbol)
        mt5_status = mt5_status_store.get()
        account = mt5_status.account
        broker_symbol = symbol_mapping.broker_symbol if symbol_mapping else ""
        mode = risk_settings.trading_mode
        latest_tick = latest_tick_override or RiskManager(self.db).latest_tick(payload.internal_symbol)
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
        trace_event(
            "order_manager",
            "order_prepared",
            source=source,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            user_id=user.id,
            symbol=payload.internal_symbol,
            broker_symbol=broker_symbol,
            mode=mode,
            side=payload.side,
            order_type=payload.order_type,
            volume=payload.volume,
            requested_price=requested_price,
            requested_sl=payload.sl,
            requested_tp=payload.tp,
            calculated_tp=effective_tp,
            tp_percent=tp_percent,
            mt5_connected=mt5_status.connected_to_mt5,
            mt5_status_updated_at=mt5_status.updated_at,
            account_login=account.login if account else None,
            account_balance=account.balance if account else None,
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
        trace_event(
            "order_manager",
            "order_record_created",
            order_id=order.id,
            source=source,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            symbol=order.internal_symbol,
            broker_symbol=order.broker_symbol,
            mode=order.mode,
            volume=order.volume,
            requested_price=order.requested_price,
            tp=order.tp,
        )

        order.status = "VALIDATING"
        if source == "STRATEGY" and strategy_key == "torum_v1" and prevalidated_risk_decision is None:
            fresh, freshness_reason, freshness = self._validate_torum_confirmation(
                strategy_signal_id=strategy_signal_id,
                symbol=order.internal_symbol,
            )
            trace_event(
                "order_manager",
                "torum_confirmation_revalidated",
                order_id=order.id,
                strategy_signal_id=strategy_signal_id,
                symbol=order.internal_symbol,
                checkpoint="before_risk",
                allowed=fresh,
                reason=freshness_reason,
                details=freshness,
            )
            if not fresh:
                return self._reject_torum_confirmation(order, mode, freshness_reason, freshness)

        risk_manager = RiskManager(self.db)
        if source == "STRATEGY" and prevalidated_risk_decision is not None:
            risk_decision = prevalidated_risk_decision
        elif source == "STRATEGY":
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
                latest_tick_override=latest_tick,
            )
        else:
            risk_decision = risk_manager.evaluate(
                order=payload,
                trading_settings=risk_settings,
                symbol_mapping=symbol_mapping,
                mt5_status=mt5_status,
                price_stale_after_seconds=app_settings.price_stale_after_seconds,
                latest_tick_override=latest_tick,
            )
            confirmation = payload.client_confirmation
            if confirmation is None or not confirmation.confirmed or not confirmation.risk_acknowledged:
                risk_decision.reasons.append("Manual trading requires explicit risk acknowledgement")
                risk_decision.allowed = False

        trace_event(
            "order_manager",
            "risk_validation_finished",
            order_id=order.id,
            source=source,
            strategy_key=strategy_key,
            strategy_signal_id=strategy_signal_id,
            symbol=order.internal_symbol,
            allowed=risk_decision.allowed,
            reasons=risk_decision.reasons,
            warnings=risk_decision.warnings,
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

        if source == "STRATEGY" and strategy_key == "torum_v1":
            fresh, freshness_reason, freshness = self._validate_torum_confirmation(
                strategy_signal_id=strategy_signal_id,
                symbol=order.internal_symbol,
            )
            trace_event(
                "order_manager",
                "torum_confirmation_revalidated",
                order_id=order.id,
                strategy_signal_id=strategy_signal_id,
                symbol=order.internal_symbol,
                checkpoint="before_execution",
                allowed=fresh,
                reason=freshness_reason,
                details=freshness,
            )
            if not fresh:
                return self._reject_torum_confirmation(order, mode, freshness_reason, freshness)

        if mode == "PAPER":
            return self._execute_paper(order, payload, latest_tick, risk_decision.warnings)

        return self._execute_mt5(
            order=order,
            payload=payload,
            warnings=risk_decision.warnings,
            magic_number=magic_number,
            deviation_points=deviation_points,
        )

    def _validate_torum_confirmation(
        self,
        *,
        strategy_signal_id: int | None,
        symbol: str,
        checked_at: datetime | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Ensure a Torum order still belongs to the latest closed M5 candle.

        Strategy evaluation and risk checks can be delayed by database load.  A
        valid bullish setup must never be sent after a newer M5 candle has
        already closed, especially when that newer candle is bearish.
        """

        real_now = checked_at or datetime.now(UTC)
        if real_now.tzinfo is None:
            real_now = real_now.replace(tzinfo=UTC)
        else:
            real_now = real_now.astimezone(UTC)
        latest_tick = self.db.scalar(
            select(Tick)
            .where(Tick.internal_symbol == symbol.upper())
            .order_by(*latest_tick_order_by())
            .limit(1)
        )
        now, market_clock_domain = resolve_market_clock(
            real_now,
            latest_tick.time if latest_tick is not None else None,
        )
        details: dict[str, Any] = {
            "checked_at": now.isoformat(),
            "checked_at_utc": real_now.isoformat(),
            "market_clock_domain": market_clock_domain,
            "latest_tick_time": latest_tick.time.isoformat() if latest_tick is not None else None,
        }
        if strategy_signal_id is None:
            return False, "missing_torum_strategy_signal", details

        signal = self.db.get(StrategySignal, strategy_signal_id)
        if signal is None or signal.strategy_key != "torum_v1":
            details["strategy_signal_id"] = strategy_signal_id
            return False, "missing_torum_strategy_signal", details

        metadata = signal.metadata_json or {}
        expected_epoch = _int_or_none(metadata.get("confirmation_candle_time"))
        details.update(
            {
                "strategy_signal_id": signal.id,
                "expected_confirmation_candle_time": expected_epoch,
            }
        )
        if expected_epoch is None:
            return False, "missing_torum_confirmation_time", details

        confirmation_age_seconds = now.timestamp() - (expected_epoch + 300)
        details["confirmation_age_seconds"] = round(confirmation_age_seconds, 3)
        maximum_execution_age_seconds = max(
            1.0,
            min(299.0, float(get_settings().torum_max_entry_delay_seconds)),
        )
        details["maximum_execution_age_seconds"] = maximum_execution_age_seconds
        # The signal is executable only during the immediately following M5
        # candle.  This also protects against a market-data gap in which the DB
        # has not yet received a newer candle to compare against.
        if confirmation_age_seconds > maximum_execution_age_seconds:
            return False, "stale_torum_confirmation_candle", details

        # M5 candle timestamps represent candle starts.  At `now`, only starts
        # at least five minutes old are closed and eligible for execution.
        latest_closed_cutoff = now - timedelta(minutes=5)
        latest = self.db.scalar(
            select(Candle)
            .where(
                Candle.internal_symbol == symbol.upper(),
                Candle.timeframe == "M5",
                Candle.time <= latest_closed_cutoff,
            )
            .order_by(Candle.time.desc())
            .limit(1)
        )
        if latest is None:
            return False, "missing_latest_closed_m5_candle", details

        latest_time = latest.time
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=UTC)
        else:
            latest_time = latest_time.astimezone(UTC)
        latest_epoch = int(latest_time.timestamp())
        params = metadata.get("params") if isinstance(metadata.get("params"), dict) else {}
        accept_doji = _bool_setting(params.get("confirmation_ignore_doji"), True)
        bullish = float(latest.close) >= float(latest.open) if accept_doji else float(latest.close) > float(latest.open)
        details.update(
            {
                "latest_closed_candle_time": latest_epoch,
                "latest_closed_candle_open": float(latest.open),
                "latest_closed_candle_close": float(latest.close),
                "latest_closed_candle_bullish": bullish,
                "accept_doji_as_bullish": accept_doji,
            }
        )
        if latest_epoch != expected_epoch:
            return False, "stale_torum_confirmation_candle", details
        if not bullish:
            return False, "torum_confirmation_candle_not_bullish", details
        return True, "torum_confirmation_current", details

    def _reject_torum_confirmation(
        self,
        order: Order,
        mode: str,
        reason: str,
        details: dict[str, Any],
    ) -> ManualOrderResponse:
        order.status = "REJECTED"
        order.rejection_reason = reason
        order.response_payload_json = {"confirmation_revalidation": details, "reason": reason}
        self.db.commit()
        return ManualOrderResponse(
            ok=False,
            order_id=order.id,
            status="REJECTED",
            mode=mode,
            message="Torum signal expired before execution",
            reasons=[reason],
            warnings=[],
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
            trace_event(
                "order_execution",
                "paper_order_rejected",
                order_id=order.id,
                symbol=order.internal_symbol,
                reason="missing_execution_price",
            )
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
            open_time_msc=int(now.timestamp() * 1000),
            enrichment_status="CONFIRMED",
            raw_payload_json={"source": "PAPER", "order_id": order.id},
        )
        self.db.add(position)
        self.db.commit()
        trace_event(
            "order_execution",
            "paper_order_executed",
            order_id=order.id,
            position_id=position.id,
            symbol=order.internal_symbol,
            side=order.side,
            volume=order.volume,
            execution_price=execution_price,
            tp=position.tp,
        )
        self._schedule_position_event("position_opened", position)
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
            # The bridge derives the first protective TP from its own live
            # execution tick. The asynchronous reconciliation may refine it
            # after the fill, but the position is never left unprotected.
            "tp": payload.tp,
            "tp_percent": payload.tp_percent,
            "deviation_points": deviation_points,
            "magic_number": magic_number,
            "comment": order.comment,
            "expected_account_login": order.account_login,
            "expected_account_server": order.account_server,
        }
        order.status = "SENT"
        self.db.flush()
        order_started = perf_counter()
        trace_event(
            "order_execution",
            "mt5_request_sent",
            order_id=order.id,
            strategy_key=order.strategy_key,
            strategy_signal_id=order.strategy_signal_id,
            symbol=order.internal_symbol,
            bridge_payload=bridge_payload,
        )
        try:
            response = self.mt5_client.execute_market_order(bridge_payload)
        except MT5BridgeClientError as exc:
            trace_exception(
                "order_execution",
                "mt5_request_failed",
                exc,
                order_id=order.id,
                symbol=order.internal_symbol,
                bridge_payload=bridge_payload,
            )
            # A POST timeout/disconnect is ambiguous: MT5 may have accepted
            # the trade before the HTTP response was lost. Keep a short
            # reservation and let position sync reconcile by the unique Torum
            # comment instead of freeing capacity and risking a duplicate buy.
            order.status = "RECONCILING"
            order.rejection_reason = str(exc)
            order.response_payload_json = {
                "ok": False,
                "error": str(exc),
                "reconciliation_required": True,
                "ambiguous_mt5_execution": True,
            }
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="RECONCILING",
                mode=order.mode,  # type: ignore[arg-type]
                message="MT5 response lost; execution is being reconciled",
                reasons=[str(exc)],
                warnings=warnings,
            )

        order.response_payload_json = response
        trace_event(
            "order_execution",
            "mt5_response_received",
            order_id=order.id,
            symbol=order.internal_symbol,
            duration_ms=round((perf_counter() - order_started) * 1000, 2),
            response=response,
        )
        if not response.get("ok"):
            raw_failure = response.get("raw") if isinstance(response.get("raw"), dict) else {}
            attempted_request = raw_failure.get("request") if isinstance(raw_failure, dict) else None
            retcode = _int_or_none(response.get("retcode"))
            ambiguous_vendor_result = (
                order.strategy_key == "torum_v1"
                and isinstance(attempted_request, dict)
                and bool(attempted_request)
                and (retcode is None or retcode == 0)
            )
            order.status = "RECONCILING" if ambiguous_vendor_result else "FAILED"
            order.rejection_reason = str(response.get("comment") or "MT5 order rejected")
            if ambiguous_vendor_result:
                order.response_payload_json = {
                    **response,
                    "reconciliation_required": True,
                    "ambiguous_mt5_execution": True,
                }
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status=order.status,
                mode=order.mode,  # type: ignore[arg-type]
                message=(
                    "MT5 result is ambiguous; execution is being reconciled"
                    if ambiguous_vendor_result
                    else "MT5 order rejected"
                ),
                reasons=[order.rejection_reason],
                warnings=warnings,
            )

        now = datetime.now(UTC)
        order.executed_at = now
        order.executed_price = _float_or_none(response.get("price"))
        order.mt5_order_ticket = _int_or_none(response.get("order"))
        order.mt5_deal_ticket = _int_or_none(response.get("deal"))
        raw_response = response.get("raw") if isinstance(response.get("raw"), dict) else {}
        bridge_resolved_snapshot = raw_response.get("resolved_position_snapshot")
        resolved = bridge_resolved_snapshot if isinstance(bridge_resolved_snapshot, dict) else None
        order.mt5_position_ticket = _int_or_none(
            response.get("position")
            or response.get("mt5_position_ticket")
            or raw_response.get("resolved_position")
        )
        if order.executed_price is None and resolved is not None:
            order.executed_price = _float_or_none(resolved.get("price_open") or resolved.get("open_price"))

        retcode = _int_or_none(response.get("retcode"))
        executed_volume = _float_or_none(response.get("volume"))
        resolved_volume = _float_or_none(resolved.get("volume")) if isinstance(resolved, dict) else None
        authoritative_volume = resolved_volume or executed_volume
        if authoritative_volume is not None and authoritative_volume > 0:
            requested_volume = float(order.volume)
            order.volume = authoritative_volume
            if retcode == 10010 or abs(authoritative_volume - requested_volume) > max(0.000001, requested_volume * 0.001):
                warnings = [*warnings, "mt5_partial_fill"] if "mt5_partial_fill" not in warnings else warnings

        # TRADE_RETCODE_PLACED confirms acceptance, not a completed market fill.
        # If MT5 has not supplied a deal or an authoritative position snapshot,
        # do not fabricate an OPEN position from the requested price. Continuous
        # sync will attach the fill or close-deal round trip moments later.
        if retcode == 10008 and order.mt5_deal_ticket is None and order.mt5_position_ticket is None and resolved is None:
            order.status = "RECONCILING"
            order.rejection_reason = "MT5 accepted the request but the market fill is still pending"
            order.response_payload_json = {
                **response,
                "reconciliation_required": True,
                "pending_market_fill": True,
            }
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="RECONCILING",
                mode=order.mode,  # type: ignore[arg-type]
                message="MT5 accepted the order; fill is being reconciled",
                reasons=[order.rejection_reason],
                warnings=warnings,
            )

        # The bridge already performs one in-process positions_get immediately
        # after a successful order_send. Do not add a second HTTP round trip on
        # the entry path. If MT5 has not exposed the fill yet, preserve the
        # ambiguous order as RECONCILING and let the continuous position sync
        # attach the authoritative ticket/price moments later.

        authoritative_opened_at = now
        authoritative_open_time_msc: int | None = None
        authoritative_position_identifier = order.mt5_position_ticket
        if isinstance(resolved, dict):
            authoritative_position_identifier = _int_or_none(resolved.get("identifier")) or authoritative_position_identifier
            authoritative_open_time_msc = _int_or_none(resolved.get("time_msc"))
            if authoritative_open_time_msc is None:
                resolved_seconds = _int_or_none(resolved.get("time"))
                authoritative_open_time_msc = resolved_seconds * 1000 if resolved_seconds else None
            if authoritative_open_time_msc:
                authoritative_opened_at = datetime.fromtimestamp(authoritative_open_time_msc / 1000, UTC)
        order.executed_at = authoritative_opened_at

        if order.executed_price is None or order.executed_price <= 0:
            trace_event(
                "order_execution",
                "mt5_execution_unresolved",
                order_id=order.id,
                symbol=order.internal_symbol,
                response=response,
                resolved_position_snapshot=resolved,
                mt5_position_ticket=order.mt5_position_ticket,
            )
            order.status = "RECONCILING"
            order.rejection_reason = "MT5 confirmed the order but no valid execution price could be resolved"
            order.response_payload_json = {
                **response,
                "reconciliation_required": True,
                "error": "missing_valid_execution_price",
            }
            self.db.commit()
            return ManualOrderResponse(
                ok=False,
                order_id=order.id,
                status="RECONCILING",
                mode=order.mode,  # type: ignore[arg-type]
                message="MT5 execution requires reconciliation",
                reasons=[order.rejection_reason],
                warnings=warnings,
            )

        order.status = "EXECUTED"
        final_tp = order.tp
        if payload.tp_percent:
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
            "resolved_position_snapshot": resolved,
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
            open_price=order.executed_price,
            current_price=order.executed_price,
            sl=order.sl,
            tp=final_tp,
            profit=0.0,
            status="OPEN",
            mt5_position_ticket=order.mt5_position_ticket,
            mt5_position_identifier=authoritative_position_identifier,
            magic_number=order.magic_number,
            opened_at=authoritative_opened_at,
            open_time_msc=authoritative_open_time_msc or int(authoritative_opened_at.timestamp() * 1000),
            enrichment_status="OPEN_CONFIRMED" if order.mt5_position_ticket else "PENDING_MT5_SYNC",
            missing_sync_count=0,
            last_seen_mt5_at=now if order.mt5_position_ticket else None,
            sync_state="CONFIRMED" if order.mt5_position_ticket else "UNRESOLVED_TICKET",
            raw_payload_json=order.response_payload_json,
        )
        self.db.add(position)
        self.db.commit()
        trace_event(
            "order_execution",
            "mt5_order_executed",
            order_id=order.id,
            position_id=position.id,
            strategy_key=order.strategy_key,
            strategy_signal_id=order.strategy_signal_id,
            symbol=order.internal_symbol,
            broker_symbol=order.broker_symbol,
            side=order.side,
            volume=order.volume,
            execution_price=order.executed_price,
            final_tp=final_tp,
            tp_status=tp_status,
            mt5_order_ticket=order.mt5_order_ticket,
            mt5_deal_ticket=order.mt5_deal_ticket,
            mt5_position_ticket=order.mt5_position_ticket,
            mt5_position_identifier=position.mt5_position_identifier,
            resolved_position_snapshot=resolved,
            duration_ms=round((perf_counter() - order_started) * 1000, 2),
        )
        self._schedule_position_event("position_opened", position)
        logger.info(
            "api_order_total_ms symbol=%s source=%s order_id=%s ms=%.2f",
            order.internal_symbol,
            order.source,
            order.id,
            (perf_counter() - order_started) * 1000,
        )
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

    def _resolve_executed_position(self, order: Order, executed_at: datetime) -> dict[str, Any] | None:
        try:
            positions = self.mt5_client.get_positions()
        except MT5BridgeClientError:
            logger.exception("mt5_position_resolution_failed order_id=%s", order.id)
            return None
        compatible: list[dict[str, Any]] = []
        for raw in positions:
            symbol = str(raw.get("symbol") or raw.get("broker_symbol") or "")
            if symbol != order.broker_symbol:
                continue
            raw_magic = _int_or_none(raw.get("magic"))
            if order.magic_number is not None and raw_magic is not None and raw_magic != order.magic_number:
                continue
            raw_volume = _float_or_none(raw.get("volume"))
            if raw_volume is None or abs(raw_volume - float(order.volume)) > max(0.000001, float(order.volume) * 0.001):
                continue
            raw_side = str(raw.get("side") or "").upper()
            raw_type = _int_or_none(raw.get("type"))
            side = raw_side if raw_side in {"BUY", "SELL"} else ("BUY" if raw_type == 0 else "SELL")
            if side != order.side:
                continue
            raw_time = _float_or_none(raw.get("time"))
            if raw_time is not None and abs(raw_time - executed_at.timestamp()) > 300:
                continue
            compatible.append(raw)
        if not compatible:
            return None
        return max(compatible, key=lambda raw: _float_or_none(raw.get("time")) or 0.0)

    def _refresh_risk_snapshot(self, symbol: str) -> None:
        try:
            RiskSnapshotService(self.db).mark_dirty(symbol)
            self.db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("risk_snapshot_mark_dirty_failed symbol=%s", symbol)

    def _schedule_position_event(self, event_type: str, position: Position) -> None:
        if self.background_tasks is None:
            return
        payload = ManualOrderPositionRead.model_validate(position).model_dump(mode="json")
        self.background_tasks.add_task(
            market_ws_manager.broadcast_position_event,
            {
                "type": event_type,
                "position_id": position.id,
                "symbol": position.internal_symbol,
                "position": payload,
                "source": "order_api",
            },
        )

    def _schedule_post_open_tasks(
        self,
        order_id: int,
        position_id: int,
        *,
        final_tp: float | None,
        tp_percent: float | None,
    ) -> None:
        position = self.db.get(Position, position_id)
        order = self.db.get(Order, order_id)
        if position is None or order is None:
            return
        if final_tp is not None:
            if position.mode == "PAPER":
                position.raw_payload_json = {**(position.raw_payload_json or {}), "tp_status": "UPDATED"}
                order.response_payload_json = {**(order.response_payload_json or {}), "tp_status": "UPDATED"}
            elif position.mt5_position_ticket is not None:
                enqueue_trade_job(
                    self.db,
                    job_type="APPLY_TP",
                    idempotency_key=f"apply-tp:{position_id}:{final_tp:.8f}",
                    payload={"position_id": position_id, "order_id": order_id, "final_tp": final_tp},
                    reactivate_completed=False,
                )
        RiskSnapshotService(self.db).mark_dirty(position.internal_symbol)
        if order.source == "STRATEGY" and order.user_id is not None:
            enqueue_trade_job(
                self.db,
                job_type="NOTIFY_ORDER",
                idempotency_key=f"notify-order:{order_id}",
                payload={"order_id": order_id},
                reactivate_completed=False,
            )
        if tp_percent:
            position.raw_payload_json = {**(position.raw_payload_json or {}), "tp_percent": tp_percent}
        self.db.commit()

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


def _bool_setting(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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

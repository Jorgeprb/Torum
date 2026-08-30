from datetime import UTC, datetime
from time import perf_counter
from dataclasses import asdict
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.decision_log import trace_event, trace_exception
from app.core.distributed_state import HybridLock
from app.mt5.status_store import mt5_status_store
from app.orders.service import OrderManager
from app.risk.manager import RiskManager
from app.settings.trading_service import get_global_trading_settings
from app.strategies.ath import latest_executable_price, plan_torum_v1_bot_exposure
from app.market_context.dollar_strength import DollarStrengthService, usd_strength_decision_for_symbol
from app.strategies.engine import StrategyContextBuilder
from app.strategies.models import StrategyConfig, StrategyRun, StrategySignal
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_definition, get_global_strategy_settings
from app.strategies.schemas import StrategyRunRead, StrategyRunResult, StrategySignalRead
from app.strategies.torum_v1 import (
    TorumV1AssetStatus,
    TorumV1StatusService,
    update_torum_entry_price_ladder,
)
from app.symbols.service import get_symbol_by_internal
from app.trading.schemas import ClientConfirmation, ManualOrderRequest
from app.users.models import User

class StrategyRunner:
    def __init__(self, db: Session, order_manager: OrderManager | None = None) -> None:
        self.db = db
        self.order_manager = order_manager or OrderManager(db)

    def run_config(
        self,
        config: StrategyConfig,
        user: User,
        *,
        prevalidated_asset_status: TorumV1AssetStatus | None = None,
    ) -> StrategyRunResult:
        pipeline_started = perf_counter()
        stage_started = pipeline_started
        stage_timings: dict[str, float] = {}
        started = datetime.now(UTC)
        run = StrategyRun(
            strategy_config_id=config.id,
            strategy_key=config.strategy_key,
            started_at=started,
            status="STARTED",
            candles_used=0,
            indicators_used_json={},
            context_summary_json={},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        stage_timings["run_record_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
        stage_started = perf_counter()
        trace_event(
            "strategy_runner",
            "run_started",
            run_id=run.id,
            config_id=config.id,
            config_revision=config.revision,
            strategy_key=config.strategy_key,
            symbol=config.internal_symbol,
            mode=config.mode,
            user_id=user.id,
            started_at=started,
        )

        settings = get_global_strategy_settings(self.db)
        if not settings.strategies_enabled:
            trace_event("strategy_runner", "run_blocked", run_id=run.id, config_id=config.id, symbol=config.internal_symbol, reason="strategies_disabled")
            return self._fail_run(run, "Strategies are disabled")
        if not config.enabled:
            trace_event("strategy_runner", "run_blocked", run_id=run.id, config_id=config.id, symbol=config.internal_symbol, reason="config_disabled")
            return self._fail_run(run, "Strategy config is disabled")

        definition = get_definition(self.db, config.strategy_key)
        if definition is None or not definition.enabled:
            trace_event("strategy_runner", "run_blocked", run_id=run.id, config_id=config.id, symbol=config.internal_symbol, reason="definition_disabled_or_missing")
            return self._fail_run(run, "Strategy definition is disabled or missing")
        if config.mode == "LIVE" and not settings.strategy_live_enabled:
            trace_event("strategy_runner", "run_blocked", run_id=run.id, config_id=config.id, symbol=config.internal_symbol, reason="strategy_live_disabled")
            return self._fail_run(run, "Strategy LIVE execution is disabled")

        # The automatic runner resolves the exact status immediately before
        # entering this method and passes it here.  Do not recalculate it on the
        # hot path: doing so duplicates H2/H3/session work and also makes direct
        # historical/manual evaluations depend on the wall-clock time of the
        # API process.  RiskManager retains the backwards-compatible fallback
        # when no prevalidated status was supplied.
        asset_status = prevalidated_asset_status
        if asset_status is not None and asset_status.status != "UNLOCKED":
            trace_event(
                "strategy_runner",
                "run_blocked",
                run_id=run.id,
                config_id=config.id,
                symbol=config.internal_symbol,
                reason="asset_not_unlocked",
                asset_status=asset_status,
            )
            return self._fail_run(run, f"Asset is not unlocked: {asset_status.reason}")
        stage_timings["preflight_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
        stage_started = perf_counter()

        lock = _torum_v1_symbol_lock(config.internal_symbol) if config.strategy_key == "torum_v1" else None
        lock_timeout = max(0.05, float(get_settings().strategy_symbol_lock_timeout_seconds))
        if lock is not None and not lock.acquire(timeout=lock_timeout):
            trace_event("strategy_runner", "run_blocked", run_id=run.id, config_id=config.id, symbol=config.internal_symbol, reason="symbol_lock_timeout")
            return self._fail_run(run, "Strategy execution is already running for this symbol")

        signal: StrategySignal | None = None
        try:
            plugin = strategy_registry.get(config.strategy_key)
            context = StrategyContextBuilder(self.db).build(config)
            stage_timings["context_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
            stage_started = perf_counter()
            signal_data = plugin.generate_signal(context)
            stage_timings["signal_generation_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
            stage_started = perf_counter()
            run.candles_used = len(context.candles)
            run.indicators_used_json = {"required": list(plugin.required_indicators), "available": list(context.indicators.keys())}
            run.context_summary_json = context.summary()
            signal = self._save_signal(config, user, signal_data)
            stage_timings["signal_persist_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
            stage_started = perf_counter()
            trace_event(
                "strategy_runner",
                "signal_saved",
                run_id=run.id,
                signal_id=signal.id,
                config_id=config.id,
                symbol=signal.internal_symbol,
                signal_type=signal.signal_type,
                side=signal.side,
                reason=signal.reason,
                suggested_volume=signal.suggested_volume,
                metadata=signal.metadata_json,
                context_summary=run.context_summary_json,
            )
            if signal.signal_type == "NONE":
                signal.status = "IGNORED"
                run.status = "FINISHED"
                run.finished_at = datetime.now(UTC)
                self.db.commit()
                trace_event(
                    "strategy_runner",
                    "run_finished_without_entry",
                    run_id=run.id,
                    signal_id=signal.id,
                    config_id=config.id,
                    symbol=signal.internal_symbol,
                    reason=signal.reason,
                    metadata=signal.metadata_json,
                )
                return StrategyRunResult(
                    ok=True,
                    run=StrategyRunRead.model_validate(run),
                    signal=StrategySignalRead.model_validate(signal),
                    message=signal.reason,
                )

            exposure_plan = None
            trading_settings = _strategy_trading_settings(get_global_trading_settings(self.db), config.mode)
            symbol_mapping = get_symbol_by_internal(self.db, signal.internal_symbol)
            latest_tick = context.latest_tick
            if signal.strategy_key == "torum_v1" and signal.signal_type == "ENTRY" and signal.side == "BUY":
                duplicate = self._previous_torum_v1_setup_signal(signal)
                if duplicate is not None:
                    trace_event(
                        "strategy_runner",
                        "entry_rejected",
                        run_id=run.id,
                        signal_id=signal.id,
                        config_id=config.id,
                        symbol=signal.internal_symbol,
                        stage="duplicate_setup",
                        reason="duplicate_setup_signal",
                        duplicate_signal_id=duplicate.id,
                        metadata=signal.metadata_json,
                    )
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": ["duplicate_setup_signal"], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected: duplicate setup",
                        reasons=["duplicate_setup_signal"],
                    )
                params = (signal.metadata_json or {}).get("params")
                normalized_params = params if isinstance(params, dict) else {}
                usd_preflight = usd_strength_decision_for_symbol(
                    signal.internal_symbol,
                    normalized_params,
                    None,
                )
                if not usd_preflight.enabled or usd_preflight.reason == "usd_strength_symbol_not_filtered":
                    # Do not scan the snapshot table when the filter is disabled
                    # or does not apply to this symbol.  In the captured incident
                    # that unnecessary query delayed an approved setup by more
                    # than a minute before any risk calculation started.
                    usd_decision = usd_preflight
                else:
                    usd_snapshot = DollarStrengthService(self.db).latest_snapshot_read()
                    usd_decision = usd_strength_decision_for_symbol(
                        signal.internal_symbol,
                        normalized_params,
                        usd_snapshot,
                    )
                signal.metadata_json = {**(signal.metadata_json or {}), **usd_decision.metadata}
                trace_event(
                    "strategy_runner",
                    "usd_filter_evaluated",
                    run_id=run.id,
                    signal_id=signal.id,
                    config_id=config.id,
                    symbol=signal.internal_symbol,
                    allowed=usd_decision.allowed,
                    reason=usd_decision.reason,
                    metadata=usd_decision.metadata,
                )
                if not usd_decision.allowed:
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": [usd_decision.reason], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected by USD strength filter",
                        reasons=[usd_decision.reason],
                    )
                latest_price = latest_executable_price(latest_tick, "BUY")
                account = mt5_status_store.get().account
                raw_desired_multiplier = int((signal.metadata_json or {}).get("desired_multiplier") or 1)
                desired_multiplier = _torum_v1_desired_multiplier_for_ath_zone(
                    self.db,
                    symbol=signal.internal_symbol,
                    current_price=latest_price,
                    params=params if isinstance(params, dict) else {},
                    desired_multiplier=raw_desired_multiplier,
                )
                plan = plan_torum_v1_bot_exposure(
                    self.db,
                    symbol=signal.internal_symbol,
                    user_id=config.user_id,
                    desired_multiplier=desired_multiplier,
                    current_price=latest_price,
                    balance=account.balance if account is not None else None,
                    trading_settings=trading_settings,
                    symbol_mapping=symbol_mapping,
                    strategy_params=params if isinstance(params, dict) else {},
                    exclude_signal_id=signal.id,
                    account_login=account.login if account is not None else None,
                    account_server=account.server if account is not None else None,
                )
                exposure_plan = plan
                stage_timings["filters_and_exposure_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
                stage_started = perf_counter()
                signal.metadata_json = {
                    **(signal.metadata_json or {}),
                    "raw_desired_multiplier": raw_desired_multiplier,
                    "desired_multiplier": desired_multiplier,
                    "accepted_multiplier": plan.multiplier,
                    "accepted_volume": plan.volume,
                    "plan_reason": plan.reason,
                    "bot_exposure_plan": asdict(plan),
                }
                trace_event(
                    "strategy_runner",
                    "exposure_plan_evaluated",
                    run_id=run.id,
                    signal_id=signal.id,
                    config_id=config.id,
                    symbol=signal.internal_symbol,
                    latest_price=latest_price,
                    account_balance=account.balance if account is not None else None,
                    raw_desired_multiplier=raw_desired_multiplier,
                    desired_multiplier=desired_multiplier,
                    plan=asdict(plan),
                )
                if not plan.allowed:
                    signal.status = "REJECTED_BY_RISK"
                    signal.risk_result_json = {"allowed": False, "reasons": [plan.reason], "warnings": []}
                    run.status = "FINISHED"
                    run.finished_at = datetime.now(UTC)
                    self.db.commit()
                    return StrategyRunResult(
                        ok=False,
                        run=StrategyRunRead.model_validate(run),
                        signal=StrategySignalRead.model_validate(signal),
                        message="Signal rejected by Torum V1 risk",
                        reasons=[plan.reason],
                    )
                signal.suggested_volume = plan.volume
                signal.status = "RISK_APPROVED"
                self.db.commit()

            order_payload = ManualOrderRequest(
                internal_symbol=signal.internal_symbol,
                side=signal.side,  # type: ignore[arg-type]
                order_type="MARKET",
                volume=signal.suggested_volume or 0.01,
                sl=signal.sl,
                tp=signal.tp,
                # Keep the final MT5 comment short, unique and identical in the
                # API and terminal. MetaTrader truncates comments to roughly 20
                # characters; the old "strategy-s<id>" format could lose the
                # last digits and made ambiguous-response reconciliation fail.
                comment=f"Torum s{signal.id}" if signal.strategy_key == "torum_v1" else f"strategy-{signal.id}",
                client_confirmation=ClientConfirmation(confirmed=True, mode_acknowledged=config.mode),
            )
            trace_event(
                "strategy_runner",
                "order_payload_prepared",
                run_id=run.id,
                signal_id=signal.id,
                config_id=config.id,
                symbol=signal.internal_symbol,
                mode=config.mode,
                order=order_payload.model_dump(mode="json"),
            )
            risk_decision = RiskManager(self.db).evaluate_strategy_order(
                order=order_payload,
                trading_settings=trading_settings,
                strategy_settings=settings,
                symbol_mapping=symbol_mapping,
                mt5_status=mt5_status_store.get(),
                price_stale_after_seconds=get_settings().price_stale_after_seconds,
                user_id=config.user_id,
                strategy_key=config.strategy_key,
                exclude_signal_id=signal.id,
                strategy_config=config,
                prevalidated_bot_status=asset_status,
                precomputed_exposure_plan=exposure_plan,
                latest_tick_override=latest_tick,
            )
            stage_timings["risk_validation_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
            stage_started = perf_counter()
            signal.risk_result_json = risk_decision.model_dump()
            trace_event(
                "strategy_runner",
                "risk_evaluated",
                run_id=run.id,
                signal_id=signal.id,
                config_id=config.id,
                symbol=signal.internal_symbol,
                allowed=risk_decision.allowed,
                reasons=risk_decision.reasons,
                warnings=risk_decision.warnings,
            )
            if not risk_decision.allowed:
                signal.status = "REJECTED_BY_RISK"
                run.status = "FINISHED"
                run.finished_at = datetime.now(UTC)
                self.db.commit()
                return StrategyRunResult(
                    ok=False,
                    run=StrategyRunRead.model_validate(run),
                    signal=StrategySignalRead.model_validate(signal),
                    message="Signal rejected by risk manager",
                    reasons=risk_decision.reasons,
                    warnings=risk_decision.warnings,
                )

            signal.status = "SENT_TO_ORDER_MANAGER"
            self.db.commit()
            trace_event(
                "strategy_runner",
                "order_manager_called",
                run_id=run.id,
                signal_id=signal.id,
                config_id=config.id,
                symbol=signal.internal_symbol,
                mode=config.mode,
                order=order_payload.model_dump(mode="json"),
            )
            order_response = self.order_manager.create_strategy_order(
                order_payload,
                user,
                strategy_key=signal.strategy_key,
                strategy_signal_id=signal.id,
                mode=config.mode,
                strategy_settings=settings,
                prevalidated_risk_decision=risk_decision,
                latest_tick_override=latest_tick,
            )
            stage_timings["order_execution_ms"] = round((perf_counter() - stage_started) * 1000.0, 3)
            stage_started = perf_counter()
            signal.order_id = order_response.order_id
            signal.status = (
                "ORDER_EXECUTED"
                if order_response.ok
                else (
                    "REJECTED_BY_RISK"
                    if order_response.status == "REJECTED"
                    else ("ORDER_RECONCILING" if order_response.status == "RECONCILING" else "ORDER_FAILED")
                )
            )
            trace_event(
                "strategy_runner",
                "order_manager_result",
                run_id=run.id,
                signal_id=signal.id,
                config_id=config.id,
                symbol=signal.internal_symbol,
                ok=order_response.ok,
                order_id=order_response.order_id,
                status=order_response.status,
                message=order_response.message,
                reasons=order_response.reasons,
                warnings=order_response.warnings,
                executed_price=order_response.executed_price,
                final_tp=order_response.final_tp,
                mt5_position_ticket=order_response.mt5_position_ticket,
                meta=order_response.meta,
                stage_timings=stage_timings,
                total_pipeline_ms=round((perf_counter() - pipeline_started) * 1000.0, 3),
            )
            if order_response.ok:
                _record_torum_v1_executed_entry_cycle(
                    config,
                    signal,
                    order_id=order_response.order_id,
                    executed_price=order_response.executed_price,
                    prior_open_positions=list(context.open_positions),
                )
            elif order_response.status != "RECONCILING":
                # A definitive MT5 rejection (for example retcode 10027 when
                # AutoTrading is disabled in the client terminal) must not burn
                # the technical setup. Release only this attempt marker so the
                # same still-valid M5 signal can be retried after the external
                # MT5 condition is corrected. Ambiguous RECONCILING responses
                # remain reserved to avoid duplicate live orders.
                _release_torum_v1_signal_attempt(config, signal)
            run.status = "FINISHED"
            run.finished_at = datetime.now(UTC)
            self.db.commit()
            total_pipeline_ms = round((perf_counter() - pipeline_started) * 1000.0, 3)
            runtime_settings = get_settings()
            hard_timeout_ms = max(1.0, float(runtime_settings.strategy_pipeline_hard_timeout_seconds) * 1000.0)
            trace_event(
                "strategy_runner",
                "pipeline_finished",
                run_id=run.id,
                signal_id=signal.id,
                order_id=order_response.order_id,
                symbol=signal.internal_symbol,
                ok=order_response.ok,
                total_pipeline_ms=total_pipeline_ms,
                stage_timings=stage_timings,
                slow=total_pipeline_ms > runtime_settings.strategy_pipeline_warn_ms,
                hard_timeout_exceeded=total_pipeline_ms > hard_timeout_ms,
                hard_timeout_ms=hard_timeout_ms,
            )
            return StrategyRunResult(
                ok=order_response.ok,
                run=StrategyRunRead.model_validate(run),
                signal=StrategySignalRead.model_validate(signal),
                message=order_response.message,
                order_id=order_response.order_id,
                reasons=order_response.reasons,
                warnings=order_response.warnings,
            )
        except Exception as exc:
            trace_exception(
                "strategy_runner",
                "run_failed",
                exc,
                run_id=run.id,
                config_id=config.id,
                symbol=config.internal_symbol,
                signal_id=signal.id if signal is not None else None,
                signal_status=signal.status if signal is not None else None,
            )
            if signal is not None and signal.status in {"RISK_APPROVED", "SENT_TO_ORDER_MANAGER"}:
                # Once the request may have crossed the API/MT5 boundary, an
                # exception is ambiguous. Keep the reservation and let the
                # position synchronizer reconcile it instead of freeing
                # capacity and risking a duplicate order on a retry/restart.
                signal.status = (
                    "ORDER_RECONCILING"
                    if signal.status == "SENT_TO_ORDER_MANAGER"
                    else "ORDER_FAILED"
                )
                signal.risk_result_json = {"allowed": False, "reasons": [str(exc)], "warnings": []}
                self.db.commit()
            return self._fail_run(run, str(exc))
        finally:
            if lock is not None:
                lock.release()

    def _save_signal(self, config: StrategyConfig, user: User, signal_data: object) -> StrategySignal:
        signal = StrategySignal(
            strategy_config_id=config.id,
            strategy_key=signal_data.strategy_key,
            user_id=user.id,
            internal_symbol=signal_data.internal_symbol,
            timeframe=signal_data.timeframe,
            signal_type=signal_data.signal_type,
            side=signal_data.side,
            entry_type=signal_data.entry_type,
            confidence=signal_data.confidence,
            suggested_volume=signal_data.suggested_volume,
            sl=signal_data.sl,
            tp=signal_data.tp,
            reason=signal_data.reason,
            metadata_json={
                **(signal_data.metadata or {}),
                "strategy_config_revision": int(config.revision or 1),
                "strategy_config_id": config.id,
            },
            status="GENERATED",
        )
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def _previous_torum_v1_setup_signal(self, signal: StrategySignal) -> StrategySignal | None:
        metadata = signal.metadata_json or {}
        confirmation_time = metadata.get("confirmation_candle_time")
        pullback_low_time = metadata.get("pullback_low_time")
        operation_zone_id = metadata.get("operation_zone_id")
        if confirmation_time is None or pullback_low_time is None:
            return None

        stmt = (
            select(StrategySignal)
            .where(
                StrategySignal.id < signal.id,
                StrategySignal.strategy_key == "torum_v1",
                StrategySignal.user_id == signal.user_id,
                StrategySignal.internal_symbol == signal.internal_symbol,
                StrategySignal.signal_type == "ENTRY",
                StrategySignal.side == "BUY",
            )
            .order_by(StrategySignal.id.desc())
            .limit(100)
        )
        duplicate_protected_statuses = {
            "RISK_APPROVED",
            "SENT_TO_ORDER_MANAGER",
            "ORDER_RECONCILING",
            "ORDER_EXECUTED",
        }
        for previous in self.db.scalars(stmt):
            if previous.status not in duplicate_protected_statuses:
                continue
            previous_metadata = previous.metadata_json or {}
            if (
                previous_metadata.get("confirmation_candle_time") == confirmation_time
                and previous_metadata.get("pullback_low_time") == pullback_low_time
                and previous_metadata.get("operation_zone_id") == operation_zone_id
            ):
                return previous
        return None

    def _fail_run(self, run: StrategyRun, message: str) -> StrategyRunResult:
        trace_event(
            "strategy_runner",
            "run_marked_failed",
            run_id=run.id,
            config_id=run.strategy_config_id,
            strategy_key=run.strategy_key,
            message=message,
        )
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error_message = message
        self.db.commit()
        self.db.refresh(run)
        return StrategyRunResult(ok=False, run=StrategyRunRead.model_validate(run), signal=None, message=message, reasons=[message])



def _release_torum_v1_signal_attempt(config: StrategyConfig, signal: StrategySignal) -> None:
    if signal.strategy_key != "torum_v1" or signal.signal_type != "ENTRY" or signal.side != "BUY":
        return
    metadata = signal.metadata_json or {}
    confirmation_time = _positive_int_or_none(metadata.get("confirmation_candle_time"))
    if confirmation_time is None:
        return
    current_params = dict(config.params_json or {})
    if _positive_int_or_none(current_params.get("last_signal_candle_time")) != confirmation_time:
        return
    for key in ("last_signal_candle_time", "last_signal_pullback_low_time", "last_signal_operation_zone_id"):
        current_params.pop(key, None)
    config.params_json = current_params
    trace_event(
        "strategy_runner",
        "signal_attempt_released_after_definitive_order_failure",
        config_id=config.id,
        signal_id=signal.id,
        symbol=signal.internal_symbol,
        confirmation_candle_time=confirmation_time,
    )


def _record_torum_v1_executed_entry_cycle(
    config: StrategyConfig,
    signal: StrategySignal,
    *,
    order_id: int | None,
    executed_price: float | None = None,
    prior_open_positions: list[object] | None = None,
) -> None:
    """Persist a pullback reset only after a Torum entry was really executed."""

    if (
        signal.strategy_key != "torum_v1"
        or signal.signal_type != "ENTRY"
        or signal.side != "BUY"
    ):
        return

    metadata = signal.metadata_json or {}
    confirmation_time = _positive_int_or_none(metadata.get("confirmation_candle_time"))
    if confirmation_time is None:
        return

    current_params = dict(config.params_json or {})
    raw_boundaries = current_params.get("executed_entry_cycle_boundaries")
    boundaries = list(raw_boundaries) if isinstance(raw_boundaries, list) else []
    normalized = {
        parsed
        for value in boundaries
        if (parsed := _positive_int_or_none(value)) is not None
    }
    normalized.add(confirmation_time)
    # The context builder loads at most a few hundred M5 bars. Keeping the most
    # recent boundaries is sufficient and avoids unbounded JSON growth.
    recent_boundaries = sorted(normalized)[-100:]

    prior_positions = list(prior_open_positions or [])
    entry_ladder = update_torum_entry_price_ladder(
        current_params,
        executed_price=executed_price,
        order_id=order_id,
        confirmation_candle_time=confirmation_time,
        prior_open_positions=prior_positions,
        reset_campaign=not prior_positions,
    )
    config.params_json = {
        **current_params,
        "last_executed_entry_candle_time": confirmation_time,
        "last_executed_entry_order_id": order_id,
        "executed_entry_cycle_boundaries": recent_boundaries,
        "executed_entry_price_ladder": entry_ladder,
    }
    trace_event(
        "strategy_runner",
        "executed_entry_cycle_recorded",
        config_id=config.id,
        signal_id=signal.id,
        symbol=signal.internal_symbol,
        order_id=order_id,
        confirmation_candle_time=confirmation_time,
        cycle_boundaries=recent_boundaries,
        entry_price_ladder=entry_ladder,
    )


def _positive_int_or_none(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

def _strategy_trading_settings(trading_settings: object, mode: str) -> object:
    return SimpleNamespace(
        trading_mode=mode,
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


def _torum_v1_symbol_lock(symbol: str) -> HybridLock:
    # Return an acquisition handle per run. Mutual exclusion still comes from
    # HybridLock's keyed process-local/Redis locks, while ownership metadata is
    # never shared between overlapping immediate and durable-fallback workers.
    return HybridLock(f"strategy:torum_v1:{symbol.upper()}")


def _torum_v1_desired_multiplier_for_ath_zone(
    db: Session,
    *,
    symbol: str,
    current_price: float | None,
    params: dict[str, object],
    desired_multiplier: int,
) -> int:
    """Keep the setup multiplier unchanged.

    ATH zones are visual/diagnostic context only.  The requested multiplier is
    selected by a visual support or by the explicit x1/x2/x3 setting on the
    Torum rectangle. ``plan_torum_v1_bot_exposure`` only degrades it to fit the
    remaining equivalent-position capacity.  The unused arguments are retained
    for compatibility with existing callers and diagnostics.
    """

    del db, symbol, current_price, params
    return max(1, min(3, int(desired_multiplier)))


def _bool_param(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
    return bool(value)

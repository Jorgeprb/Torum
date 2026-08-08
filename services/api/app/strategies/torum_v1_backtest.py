from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.no_trade_zones.models import NoTradeZone
from app.strategies.ath import ath_zone_for_price_config
from app.strategies.models import StrategyConfig
from app.strategies.schemas import (
    TorumV1BacktestCandleRead,
    TorumV1BacktestDebugEventRead,
    TorumV1BacktestEquityPointRead,
    TorumV1BacktestMetricsRead,
    TorumV1BacktestPullbackRead,
    TorumV1BacktestRead,
    TorumV1BacktestRequest,
    TorumV1BacktestSupportRead,
    TorumV1BacktestTradeRead,
    TorumV1BacktestZoneRead,
)
from app.strategies.torum_v1 import (
    TorumV1OperationZone,
    TorumV1StatusService,
    TorumV1SupportZone,
    pullback_debug_payload,
    is_price_inside_operation_zone,
    is_time_inside_operation_zone,
    operation_zones_from_drawings,
    should_buy_torum_v1,
    support_zones_from_drawings,
    update_torum_entry_price_ladder,
)
from app.strategies.torum_v1_config import TorumV1Params
from app.symbols.models import SymbolMapping


class TorumV1BacktestCancelled(RuntimeError):
    """Raised when a historical simulation is cancelled by its caller."""


ProgressCallback = Callable[[float, str, str], None]
CancelCheck = Callable[[], bool]


@dataclass(slots=True)
class _OpenTrade:
    id: str
    entry_time: datetime
    entry_index: int
    entry_price: float
    tp_price: float
    volume: float
    multiplier: int
    support_level: int | None
    support_zone_id: str | None
    operation_zone_id: str | None
    pullback_pct: float | None
    pullback_low: float | None
    pullback_low_time: datetime | None
    balance_before: float
    risk_at_entry: float | None
    ath_zone: str | None
    active_from_index: int
    status: str = "OPEN"
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    bars_held: int = 0
    gross_profit: float = 0.0
    commission: float = 0.0
    net_profit: float = 0.0
    return_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    balance_after: float | None = None


@dataclass(slots=True)
class _DxyPoint:
    close_time: datetime
    open: float
    close: float
    sma: float | None
    close_n_days_ago: float | None


class TorumV1BacktestEngine:
    """Side-effect-free historical simulator for Torum V1.

    The engine deliberately does not create orders, signals, positions or jobs.
    It reuses the production technical decision function and reconstructs the
    surrounding filters with historical data where Torum persists enough input.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(
        self,
        config: StrategyConfig,
        request: TorumV1BacktestRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> TorumV1BacktestRead:
        started = perf_counter()
        self._check_cancel(cancel_check)
        self._progress(progress_callback, 0.01, "PREPARING", "Validando configuración")
        symbol = request.symbol.upper()
        params = TorumV1Params.normalize(
            symbol,
            {**(config.params_json or {}), **(request.params or {})},
        ).model_dump()
        # Production writes deduplication state into params_json after a live
        # signal.  A historical run must start with a clean state; otherwise a
        # recent live setup can silently suppress the matching historical bar.
        for runtime_key in (
            "last_signal_candle_time",
            "last_signal_pullback_low_time",
            "last_signal_operation_zone_id",
            "last_executed_entry_candle_time",
            "last_executed_entry_order_id",
            "executed_entry_cycle_boundaries",
            "executed_entry_price_ladder",
        ):
            params.pop(runtime_key, None)
        params["use_news"] = bool(request.use_news and params.get("use_news", True))
        params["usd_strength_filter_enabled"] = bool(
            request.use_dxy and params.get("usd_strength_filter_enabled", True)
        )
        if not request.use_operation_zones:
            params["enable_operation_zones"] = False
            params["require_zone"] = False

        candles = self._load_candles(symbol, request)
        if len(candles) < 3:
            raise ValueError("not_enough_m5_candles_for_backtest")
        self._check_cancel(cancel_check)
        self._progress(
            progress_callback,
            0.06,
            "LOADING_MARKET",
            f"{len(candles)} velas M5 cargadas",
        )

        drawings = self._load_drawings(config)
        drawing_names = {drawing.id: drawing.name for drawing in drawings}
        operation_zones = operation_zones_from_drawings(drawings)
        supports = support_zones_from_drawings(drawings)
        operation_zones = self._select_operation_zones(operation_zones, request)
        supports = self._select_supports(supports, request)

        news_zones = self._load_news_zones(symbol, candles) if request.use_news else []
        dxy_points = self._load_dxy_points(candles, params) if request.use_dxy else []
        self._check_cancel(cancel_check)
        self._progress(
            progress_callback,
            0.12,
            "LOADING_CONTEXT",
            "Regiones, soportes, noticias, DXY y ATH preparados",
        )
        dxy_times = [point.close_time for point in dxy_points]

        mapping = self.db.scalar(
            select(SymbolMapping).where(SymbolMapping.internal_symbol == symbol)
        )
        point = float(mapping.point) if mapping is not None and mapping.point > 0 else 0.01
        contract_size = (
            float(mapping.contract_size)
            if mapping is not None and mapping.contract_size > 0
            else 100.0
        )
        conversion_rate = (
            float(mapping.risk_conversion_rate)
            if mapping is not None and mapping.risk_conversion_rate > 0
            else 1.0
        )
        effective_contract_size = contract_size * conversion_rate

        prior_ath = self.db.scalar(
            select(func.max(Candle.high)).where(
                Candle.internal_symbol == symbol,
                Candle.timeframe == "M5",
                Candle.time < _utc(candles[0].time),
            )
        )
        running_ath = max(float(prior_ath or 0.0), float(candles[0].high))

        status_service = TorumV1StatusService(self.db)
        unlock_timeline = (
            self._build_unlock_timeline(status_service, symbol, candles, params)
            if request.use_unlock
            else {}
        )
        self._check_cancel(cancel_check)
        self._progress(
            progress_callback,
            0.16,
            "PRECOMPUTING",
            "Contexto temporal y desbloqueos preparados",
        )
        balance = float(request.initial_balance)
        open_trades: list[_OpenTrade] = []
        all_trades: list[_OpenTrade] = []
        equity_curve: list[TorumV1BacktestEquityPointRead] = []
        debug_events: list[TorumV1BacktestDebugEventRead] = []
        rejection_counts: dict[str, int] = {}
        seen_pullback_keys: set[int] = set()
        signals_detected = 0
        blocked_signals = 0
        bars_with_exposure = 0
        max_concurrent_trades = 0
        peak_equity = balance
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        trade_seq = 0
        debug_truncated = False
        lookback_window = max(
            120,
            min(1000, int(params.get("pullback_lookback_bars", 12)) * 16),
        )

        progress_stride = max(1, len(candles) // 200)
        for index, candle in enumerate(candles):
            if index % progress_stride == 0:
                self._check_cancel(cancel_check)
                fraction = index / max(1, len(candles))
                self._progress(
                    progress_callback,
                    0.16 + fraction * 0.72,
                    "SIMULATING",
                    f"Evaluando vela {index + 1} de {len(candles)}",
                )
            candle_time = _utc(candle.time)
            candle_close_time = candle_time + timedelta(minutes=5)
            running_ath = max(running_ath, float(candle.high))

            # Activate NEXT_OPEN trades and allow the TP to be hit within that bar.
            active_trades = [trade for trade in open_trades if trade.active_from_index <= index]
            if active_trades:
                bars_with_exposure += 1
            max_concurrent_trades = max(max_concurrent_trades, len(active_trades))
            for trade in list(active_trades):
                trade.bars_held = max(1, index - trade.entry_index + 1)
                if trade.entry_price > 0:
                    trade.mfe_pct = max(
                        trade.mfe_pct,
                        (float(candle.high) - trade.entry_price) / trade.entry_price * 100.0,
                    )
                    trade.mae_pct = min(
                        trade.mae_pct,
                        (float(candle.low) - trade.entry_price) / trade.entry_price * 100.0,
                    )
                if float(candle.high) >= trade.tp_price:
                    balance = self._close_trade(
                        trade,
                        exit_time=candle_time,
                        exit_price=trade.tp_price,
                        exit_reason="TAKE_PROFIT",
                        balance=balance,
                        effective_contract_size=effective_contract_size,
                        commission_per_lot=request.commission_per_lot,
                    )
                    open_trades.remove(trade)
                    self._debug(
                        debug_events,
                        request,
                        time_=candle_time,
                        candle_index=index,
                        stage="exit",
                        status="EXIT",
                        reason_code="take_profit",
                        summary=f"TP alcanzado en {trade.tp_price:.4f}",
                        price=trade.tp_price,
                        details={"trade_id": trade.id, "net_profit": trade.net_profit},
                    )

            if index >= 2:
                confirmation_time = candle_close_time + timedelta(seconds=1)
                first_rejection: tuple[str, str, dict[str, Any]] | None = None

                if request.use_session and not _session_allows(params, confirmation_time):
                    first_rejection = (
                        "outside_session",
                        "Fuera del horario configurado",
                        {},
                    )
                elif request.use_news and _news_blocks(news_zones, confirmation_time):
                    first_rejection = (
                        "news_zone",
                        "Bloqueado por una zona de noticias histórica",
                        {},
                    )

                window = candles[max(0, index - lookback_window + 1) : index + 1]
                decision = None
                if first_rejection is None:
                    decision = should_buy_torum_v1(
                        symbol=symbol,
                        candles_m5=window,
                        operation_zones=operation_zones,
                        support_zones=supports if request.use_supports else [],
                        params=params,
                        now=confirmation_time,
                        open_positions=list(open_trades),
                        current_price=float(candle.close),
                    )
                    if not decision.should_buy:
                        first_rejection = (
                            decision.reason,
                            _reason_text(decision.reason),
                            _decision_details(decision),
                        )

                if first_rejection is None and decision is not None and decision.metadata is not None:
                    signals_detected += 1
                    pullback_key = int(decision.metadata.get("pullback_low_time") or 0)
                    if pullback_key in seen_pullback_keys:
                        first_rejection = (
                            "duplicate_signal_pullback",
                            "El pullback ya generó una entrada en esta simulación",
                            {"pullback_low_time": pullback_key},
                        )
                    else:
                        seen_pullback_keys.add(pullback_key)

                if first_rejection is None and request.use_unlock:
                    madrid_now = confirmation_time.astimezone(_MADRID)
                    unlocked_at, unlock_reason = unlock_timeline.get(
                        madrid_now.date(),
                        (None, "missing_unlock_day"),
                    )
                    if unlocked_at is None or confirmation_time < unlocked_at:
                        effective_reason = (
                            "waiting_closed_candle"
                            if unlocked_at is not None and confirmation_time < unlocked_at
                            else unlock_reason
                        )
                        first_rejection = (
                            effective_reason,
                            _reason_text(effective_reason),
                            {
                                "unlocked_at": unlocked_at.isoformat() if unlocked_at is not None else None,
                                "day_result": unlock_reason,
                            },
                        )

                dxy_result: dict[str, Any] = {"allowed": True, "reason": "disabled"}
                if first_rejection is None and request.use_dxy:
                    dxy_result = _historical_dxy_decision(
                        symbol,
                        params,
                        confirmation_time,
                        dxy_points,
                        dxy_times,
                    )
                    if not bool(dxy_result["allowed"]):
                        first_rejection = (
                            str(dxy_result["reason"]),
                            _reason_text(str(dxy_result["reason"])),
                            dxy_result,
                        )

                if first_rejection is not None:
                    reason, summary, details = first_rejection
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                    if decision is not None and decision.should_buy:
                        blocked_signals += 1
                    self._debug(
                        debug_events,
                        request,
                        time_=confirmation_time,
                        candle_index=index,
                        stage=_stage_for_reason(reason),
                        status="REJECT",
                        reason_code=reason,
                        summary=summary,
                        price=float(candle.close),
                        details=details,
                    )
                elif decision is not None and decision.should_buy and decision.metadata is not None:
                    requested_multiplier = max(
                        1,
                        int(decision.metadata.get("desired_multiplier") or 1),
                    )
                    entry_index = index if request.entry_model == "CONFIRMATION_CLOSE" else index + 1
                    if entry_index >= len(candles):
                        rejection_counts["missing_next_open"] = rejection_counts.get("missing_next_open", 0) + 1
                    else:
                        raw_entry = (
                            float(candle.close)
                            if request.entry_model == "CONFIRMATION_CLOSE"
                            else float(candles[entry_index].open)
                        )
                        entry_price = raw_entry + (
                            float(request.spread_points) + float(request.slippage_points)
                        ) * point
                        entry_time = (
                            confirmation_time
                            if request.entry_model == "CONFIRMATION_CLOSE"
                            else _utc(candles[entry_index].time)
                        )
                        zone_entry_required = (
                            request.use_operation_zones
                            and bool(params.get("require_zone", True))
                            and decision.zone is not None
                        )
                        allow_confirmation_price_outside = bool(
                            params.get("operation_zone_allow_confirmation_price_outside", False)
                        )
                        entry_geometry_ok = True
                        if zone_entry_required:
                            entry_time_inside = is_time_inside_operation_zone(
                                checked_at=entry_time,
                                zone=decision.zone,
                                time_tolerance_minutes=int(
                                    params.get("operation_zone_time_tolerance_minutes", 0) or 0
                                ),
                            )
                            entry_price_inside = is_price_inside_operation_zone(
                                price=entry_price,
                                zone=decision.zone,
                                price_tolerance_pct=float(
                                    params.get("operation_zone_price_tolerance_pct", 0.0) or 0.0
                                ),
                            )
                            entry_geometry_ok = entry_time_inside and (
                                entry_price_inside or allow_confirmation_price_outside
                            )
                            if not entry_geometry_ok:
                                reason_code = (
                                    "entry_time_outside_operation_zone"
                                    if not entry_time_inside
                                    else "entry_price_outside_operation_zone"
                                )
                                blocked_signals += 1
                                rejection_counts[reason_code] = rejection_counts.get(reason_code, 0) + 1
                                self._debug(
                                    debug_events,
                                    request,
                                    time_=entry_time,
                                    candle_index=entry_index,
                                    stage="execution",
                                    status="REJECT",
                                    reason_code=reason_code,
                                    summary=_reason_text(reason_code),
                                    price=entry_price,
                                    details={
                                        "operation_zone_id": decision.zone.drawing_id,
                                        "zone_price_min": decision.zone.price_min,
                                        "zone_price_max": decision.zone.price_max,
                                        "zone_time1": decision.zone.time1,
                                        "zone_time2": decision.zone.time2,
                                        "entry_model": request.entry_model,
                                        "entry_time_inside": entry_time_inside,
                                        "entry_price_inside": entry_price_inside,
                                        "allow_confirmation_price_outside": allow_confirmation_price_outside,
                                    },
                                )

                        if entry_geometry_ok:
                            accepted_multiplier, risk_value, ath_zone, block_reason = self._size_entry(
                                params=params,
                                requested_multiplier=requested_multiplier,
                                open_trades=list(open_trades),
                                entry_price=entry_price,
                                running_ath=running_ath,
                                balance=balance,
                                effective_contract_size=effective_contract_size,
                                use_ath_capacity=request.use_ath_capacity,
                                use_risk=request.use_risk,
                            )
                            if accepted_multiplier <= 0:
                                blocked_signals += 1
                                rejection_counts[block_reason] = rejection_counts.get(block_reason, 0) + 1
                                self._debug(
                                    debug_events,
                                    request,
                                    time_=confirmation_time,
                                    candle_index=index,
                                    stage="risk",
                                    status="REJECT",
                                    reason_code=block_reason,
                                    summary=_reason_text(block_reason),
                                    price=entry_price,
                                    details={
                                        "requested_multiplier": requested_multiplier,
                                        "risk": risk_value,
                                        "ath_zone": ath_zone,
                                    },
                                )
                            else:
                                trade_seq += 1
                                volume = float(params.get("suggested_volume", 0.01)) * accepted_multiplier
                                tp_price = entry_price * (
                                    1.0 + float(params.get("take_profit_percent", 0.09)) / 100.0
                                )
                                trade = _OpenTrade(
                                    id=f"BT-{trade_seq:04d}",
                                    entry_time=entry_time,
                                    entry_index=entry_index,
                                    entry_price=entry_price,
                                    tp_price=tp_price,
                                    volume=volume,
                                    multiplier=accepted_multiplier,
                                    support_level=_int_or_none(decision.metadata.get("support_level")),
                                    support_zone_id=_str_or_none(decision.metadata.get("support_zone_id")),
                                    operation_zone_id=_str_or_none(decision.metadata.get("operation_zone_id")),
                                    pullback_pct=_float_or_none(decision.metadata.get("pullback_pct")),
                                    pullback_low=_float_or_none(decision.metadata.get("pullback_low")),
                                    pullback_low_time=_timestamp_or_none(decision.metadata.get("pullback_low_time")),
                                    balance_before=balance,
                                    risk_at_entry=risk_value,
                                    ath_zone=ath_zone,
                                    active_from_index=entry_index if request.entry_model == "NEXT_OPEN" else index + 1,
                                )
                                prior_open_trades = list(open_trades)
                                open_trades.append(trade)
                                all_trades.append(trade)
                                _record_backtest_entry_cycle(
                                    params,
                                    decision.metadata,
                                    entry_price=entry_price,
                                    prior_open_trades=prior_open_trades,
                                )
                                self._debug(
                                    debug_events,
                                    request,
                                    time_=entry_time,
                                    candle_index=entry_index,
                                    stage="execution",
                                    status="ENTRY",
                                    reason_code="entry_opened",
                                    summary=f"Compra x{accepted_multiplier} a {entry_price:.4f}",
                                    price=entry_price,
                                    details={
                                        "trade_id": trade.id,
                                        "tp": tp_price,
                                        "volume": volume,
                                        "requested_multiplier": requested_multiplier,
                                        "accepted_multiplier": accepted_multiplier,
                                        "support_level": trade.support_level,
                                        "operation_zone_id": trade.operation_zone_id,
                                        "dxy": dxy_result,
                                    },
                                )

            active_for_equity = [trade for trade in open_trades if trade.active_from_index <= index]
            unrealized = sum(
                (float(candle.close) - trade.entry_price)
                * trade.volume
                * effective_contract_size
                for trade in active_for_equity
            )
            equity = balance + unrealized
            peak_equity = max(peak_equity, equity)
            drawdown = max(0.0, peak_equity - equity)
            drawdown_pct = drawdown / peak_equity * 100.0 if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            equity_curve.append(
                TorumV1BacktestEquityPointRead(
                    time=candle_close_time,
                    balance=round(balance, 8),
                    equity=round(equity, 8),
                    drawdown=round(drawdown, 8),
                    drawdown_pct=round(drawdown_pct, 6),
                    open_trades=len(active_for_equity),
                )
            )

            if len(debug_events) >= request.max_debug_events:
                debug_truncated = True

        self._check_cancel(cancel_check)
        self._progress(
            progress_callback,
            0.90,
            "FINALIZING",
            "Cerrando operaciones y calculando métricas",
        )
        if request.close_open_trades_at_end and open_trades:
            final_candle = candles[-1]
            final_time = _utc(final_candle.time) + timedelta(minutes=5)
            final_price = float(final_candle.close) - float(request.slippage_points) * point
            for trade in list(open_trades):
                if trade.active_from_index >= len(candles):
                    continue
                trade.bars_held = max(1, len(candles) - trade.entry_index)
                balance = self._close_trade(
                    trade,
                    exit_time=final_time,
                    exit_price=final_price,
                    exit_reason="END_OF_DATA",
                    balance=balance,
                    effective_contract_size=effective_contract_size,
                    commission_per_lot=request.commission_per_lot,
                )
                open_trades.remove(trade)
                self._debug(
                    debug_events,
                    request,
                    time_=final_time,
                    candle_index=len(candles) - 1,
                    stage="exit",
                    status="EXIT",
                    reason_code="end_of_data",
                    summary="Cierre forzado al final de los datos",
                    price=final_price,
                    details={"trade_id": trade.id, "net_profit": trade.net_profit},
                )

        final_equity = balance
        if open_trades:
            final_close = float(candles[-1].close)
            final_equity += sum(
                (final_close - trade.entry_price) * trade.volume * effective_contract_size
                for trade in open_trades
                if trade.active_from_index < len(candles)
            )

        pullbacks = pullback_debug_payload(
            candles,
            {
                **params,
                "pullback_min_pct": float(params.get("pullback_entry_min_pct", 0.20)),
                "pullback_live_update_enabled": False,
                "pullback_max_count": max(1, len(candles)),
            },
        )

        metrics = self._metrics(
            request=request,
            trades=all_trades,
            open_trades=open_trades,
            initial_balance=float(request.initial_balance),
            final_balance=balance,
            final_equity=final_equity,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            bars_with_exposure=bars_with_exposure,
            candles_count=len(candles),
            max_concurrent_trades=max_concurrent_trades,
            trading_days=len({_utc(item.time).date() for item in candles}),
            signals_detected=signals_detected,
            blocked_signals=blocked_signals,
            rejection_counts=rejection_counts,
        )

        warnings: list[str] = []
        if debug_truncated:
            warnings.append(
                f"La traza se limitó a {request.max_debug_events} eventos; aumenta el límite para depuración completa."
            )
        if request.use_dxy and not dxy_points:
            warnings.append("No hay histórico DXY suficiente; se aplicó la política de datos desconocidos.")
        if not request.close_open_trades_at_end and open_trades:
            warnings.append("Hay operaciones abiertas al final; el balance final no incluye su resultado no realizado.")
        if request.entry_model == "CONFIRMATION_CLOSE":
            warnings.append("La entrada al cierre es idealizada; NEXT_OPEN es más conservador.")
        if request.use_operation_zones and not operation_zones:
            warnings.append("Regiones activadas sin ninguna región seleccionada: no se producirán entradas que requieran zona.")
        if request.use_supports and not supports:
            warnings.append("Soportes activados sin soportes seleccionados: las entradas se simulan sin multiplicador de soporte.")
        if any(trade.exit_reason == "TAKE_PROFIT" for trade in all_trades):
            warnings.append("La hora intravela del TP no está disponible en velas M5; la salida se ancla al inicio de la vela que tocó el TP.")

        zone_reads = [
            TorumV1BacktestZoneRead(
                id=zone.drawing_id,
                name=drawing_names.get(zone.drawing_id),
                direction=zone.direction,
                time1=datetime.fromtimestamp(zone.time1, UTC),
                time2=datetime.fromtimestamp(zone.time2, UTC) if zone.time2 is not None else None,
                price_min=zone.price_min,
                price_max=zone.price_max,
                selected=True,
            )
            for zone in operation_zones
        ]
        support_reads = [
            TorumV1BacktestSupportRead(
                id=support.drawing_id,
                name=drawing_names.get(support.drawing_id),
                level=support.level,
                price=support.price,
                lower_price=support.lower_price,
                upper_price=support.upper_price,
                enabled=support.enabled,
                selected=True,
            )
            for support in supports
        ]

        self._check_cancel(cancel_check)
        elapsed_ms = (perf_counter() - started) * 1000.0
        result = TorumV1BacktestRead(
            symbol=symbol,
            generated_at=datetime.now(UTC),
            from_time=_utc(candles[0].time),
            to_time=_utc(candles[-1].time) + timedelta(minutes=5),
            candles_analyzed=len(candles),
            candles=[
                TorumV1BacktestCandleRead(
                    time=_utc(item.time),
                    open=float(item.open),
                    high=float(item.high),
                    low=float(item.low),
                    close=float(item.close),
                    volume=float(item.volume) if item.volume is not None else None,
                )
                for item in candles
            ],
            trades=[self._trade_read(trade) for trade in all_trades],
            equity_curve=equity_curve,
            operation_zones=zone_reads,
            supports=support_reads,
            pullbacks=[
                TorumV1BacktestPullbackRead(
                    swing_high_time=datetime.fromtimestamp(int(item["swing_high_time"]), UTC),
                    swing_high=float(item["swing_high"]),
                    pullback_low_time=datetime.fromtimestamp(int(item["pullback_low_time"]), UTC),
                    pullback_low=float(item["pullback_low"]),
                    pullback_pct=float(item["pullback_pct"]),
                    is_live=bool(item["is_live"]),
                )
                for item in pullbacks
            ],
            debug_events=debug_events,
            metrics=metrics,
            configuration={
                "params": params,
                "request": request.model_dump(mode="json"),
                "point": point,
                "contract_size": contract_size,
                "risk_conversion_rate": conversion_rate,
                "effective_contract_size": effective_contract_size,
            },
            coverage={
                "candles": "historical M5",
                "session": "historical" if request.use_session else "disabled",
                "unlock": "historical H2/H3 aggregation" if request.use_unlock else "disabled",
                "news": "historical no-trade zones" if request.use_news else "disabled",
                "dxy": "historical D1 + SMA" if request.use_dxy else "disabled",
                "operation_zones": "selected manual drawings" if request.use_operation_zones else "disabled",
                "supports": "selected support drawings" if request.use_supports else "disabled",
                "ath_capacity": "running historical ATH" if request.use_ath_capacity else "disabled",
                "risk": "simulated balance and open exposure" if request.use_risk else "disabled",
                "execution": request.entry_model,
                "orders": "never sent",
            },
            warnings=warnings,
            config_revision=int(config.revision or 1),
            elapsed_ms=round(elapsed_ms, 3),
        )
        self._progress(progress_callback, 1.0, "COMPLETED", "Simulación completada")
        return result

    @staticmethod
    def _check_cancel(cancel_check: CancelCheck | None) -> None:
        if cancel_check is not None and cancel_check():
            raise TorumV1BacktestCancelled("backtest_cancelled")

    @staticmethod
    def _progress(
        callback: ProgressCallback | None,
        value: float,
        stage: str,
        message: str,
    ) -> None:
        if callback is not None:
            callback(max(0.0, min(1.0, float(value))), stage, message)

    def _build_unlock_timeline(
        self,
        status_service: TorumV1StatusService,
        symbol: str,
        candles: list[Candle],
        params: dict[str, Any],
    ) -> dict[object, tuple[datetime | None, str]]:
        """Precompute one deterministic unlock result per Madrid trading day.

        Calling the production status service for every M5 candle performs several
        database aggregations per bar.  The unlock rule is monotonic within a day:
        once a qualifying H2/H3 window closes, the asset remains unlocked.  We can
        therefore calculate the earliest unlock once at the end of each day and
        compare historical candle times against that timestamp without look-ahead.
        """
        session_start = str(params.get("session_start") or "00:00")
        session_end = str(params.get("session_end") or "23:59")
        result: dict[object, tuple[datetime | None, str]] = {}
        days = sorted({_utc(item.time).astimezone(_MADRID).date() for item in candles})
        try:
            end_hour, end_minute = map(int, session_end.split(":"))
        except (TypeError, ValueError):
            end_hour, end_minute = 23, 59
        try:
            start_hour, start_minute = map(int, session_start.split(":"))
        except (TypeError, ValueError):
            start_hour, start_minute = 0, 0

        for day in days:
            day_end = datetime(
                day.year, day.month, day.day, end_hour, end_minute, tzinfo=_MADRID
            )
            if (end_hour, end_minute) <= (start_hour, start_minute):
                day_end += timedelta(days=1)
            try:
                result[day] = status_service._unlocked_at(  # noqa: SLF001 - deterministic simulator reuse
                    symbol,
                    day_end + timedelta(seconds=1),
                    session_start,
                    session_end,
                    params,
                )
            except Exception as exc:  # simulation must explain missing historical coverage
                result[day] = (None, f"unlock_evaluation_error:{type(exc).__name__}")
        return result

    def _load_candles(
        self,
        symbol: str,
        request: TorumV1BacktestRequest,
    ) -> list[Candle]:
        stmt = select(Candle).where(
            Candle.internal_symbol == symbol,
            Candle.timeframe == "M5",
        )
        if request.from_time is not None:
            stmt = stmt.where(Candle.time >= _utc(request.from_time))
        if request.to_time is not None:
            stmt = stmt.where(Candle.time <= _utc(request.to_time))
        rows = list(
            self.db.scalars(
                stmt.order_by(Candle.time.desc()).limit(request.candle_limit)
            )
        )
        rows.reverse()
        return rows

    def _load_drawings(self, config: StrategyConfig) -> list[ChartDrawing]:
        return list(
            self.db.scalars(
                select(ChartDrawing).where(
                    ChartDrawing.user_id == config.user_id,
                    ChartDrawing.internal_symbol == config.internal_symbol,
                    ChartDrawing.drawing_type.in_(("rectangle", "manual_zone", "horizontal_line")),
                    ChartDrawing.visible.is_(True),
                    ChartDrawing.source == "MANUAL",
                    ChartDrawing.deleted_at.is_(None),
                )
            )
        )

    def _select_operation_zones(
        self,
        zones: list[TorumV1OperationZone],
        request: TorumV1BacktestRequest,
    ) -> list[TorumV1OperationZone]:
        if not request.use_operation_zones:
            return []
        selected = set(request.selected_operation_zone_ids)
        return [zone for zone in zones if zone.drawing_id in selected]

    def _select_supports(
        self,
        supports: list[TorumV1SupportZone],
        request: TorumV1BacktestRequest,
    ) -> list[TorumV1SupportZone]:
        if not request.use_supports:
            return []
        selected = set(request.selected_support_zone_ids)
        return [support for support in supports if support.drawing_id in selected]

    def _load_news_zones(
        self,
        symbol: str,
        candles: list[Candle],
    ) -> list[NoTradeZone]:
        return list(
            self.db.scalars(
                select(NoTradeZone).where(
                    NoTradeZone.internal_symbol == symbol,
                    NoTradeZone.enabled.is_(True),
                    NoTradeZone.end_time >= _utc(candles[0].time),
                    NoTradeZone.start_time <= _utc(candles[-1].time) + timedelta(minutes=5),
                )
            )
        )

    def _load_dxy_points(
        self,
        candles: list[Candle],
        params: dict[str, Any],
    ) -> list[_DxyPoint]:
        period = max(2, int(params.get("usd_sma_period", 30)))
        lookback = max(1, int(params.get("usd_strong_drop_lookback_days", 3)))
        start = _utc(candles[0].time) - timedelta(days=period + lookback + 10)
        end = _utc(candles[-1].time) + timedelta(days=2)
        rows = list(
            self.db.scalars(
                select(Candle)
                .where(
                    Candle.internal_symbol == "DXY",
                    Candle.timeframe == "D1",
                    Candle.time >= start,
                    Candle.time <= end,
                )
                .order_by(Candle.time)
            )
        )
        closes: list[float] = []
        result: list[_DxyPoint] = []
        for index, row in enumerate(rows):
            closes.append(float(row.close))
            sma = sum(closes[-period:]) / period if len(closes) >= period else None
            close_n = closes[index - lookback] if index >= lookback else None
            result.append(
                _DxyPoint(
                    close_time=_utc(row.time) + timedelta(days=1),
                    open=float(row.open),
                    close=float(row.close),
                    sma=sma,
                    close_n_days_ago=close_n,
                )
            )
        return result

    def _size_entry(
        self,
        *,
        params: dict[str, Any],
        requested_multiplier: int,
        open_trades: list[_OpenTrade],
        entry_price: float,
        running_ath: float,
        balance: float,
        effective_contract_size: float,
        use_ath_capacity: bool,
        use_risk: bool,
    ) -> tuple[int, float | None, str | None, str]:
        base_volume = float(params.get("suggested_volume", 0.01))
        configured_max = max(1, int(params.get("max_equivalent_positions", 3)))
        used_equivalent = sum(max(1, trade.multiplier) for trade in open_trades)
        max_equivalent = configured_max
        ath_zone_key: str | None = None
        if use_ath_capacity:
            zone = ath_zone_for_price_config(running_ath, entry_price, params)
            if zone is not None:
                ath_zone_key = zone.key
                max_equivalent = min(max_equivalent, int(zone.max_lot_equivalents))
        available = max(0, max_equivalent - used_equivalent)
        if available <= 0:
            return 0, None, ath_zone_key, "ath_or_position_capacity_exceeded"

        requested = min(max(1, requested_multiplier), available)
        if not bool(params.get("support_degrade_enabled", True)) and requested < requested_multiplier:
            return 0, None, ath_zone_key, "requested_multiplier_does_not_fit"

        stress_price = running_ath * (
            1.0 - float(params.get("risk_stress_drop_from_ath_pct", 30.0)) / 100.0
        )
        max_loss = balance * float(params.get("risk_max_balance_pct", 50.0)) / 100.0
        open_loss = sum(
            max(0.0, trade.entry_price - stress_price)
            * trade.volume
            * effective_contract_size
            for trade in open_trades
        )

        for multiplier in range(requested, 0, -1):
            volume = base_volume * multiplier
            candidate_loss = (
                max(0.0, entry_price - stress_price)
                * volume
                * effective_contract_size
            )
            projected = open_loss + candidate_loss
            if not use_risk or projected <= max_loss:
                return multiplier, projected if use_risk else None, ath_zone_key, "allowed"
            if not bool(params.get("support_degrade_enabled", True)):
                break
        return 0, open_loss, ath_zone_key, "risk_limit_exceeded"

    def _close_trade(
        self,
        trade: _OpenTrade,
        *,
        exit_time: datetime,
        exit_price: float,
        exit_reason: str,
        balance: float,
        effective_contract_size: float,
        commission_per_lot: float,
    ) -> float:
        trade.status = "CLOSED"
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.gross_profit = (
            (exit_price - trade.entry_price)
            * trade.volume
            * effective_contract_size
        )
        trade.commission = float(commission_per_lot) * trade.volume
        trade.net_profit = trade.gross_profit - trade.commission
        trade.return_pct = (
            (exit_price - trade.entry_price) / trade.entry_price * 100.0
            if trade.entry_price > 0
            else 0.0
        )
        trade.balance_after = balance + trade.net_profit
        return trade.balance_after

    def _trade_read(self, trade: _OpenTrade) -> TorumV1BacktestTradeRead:
        return TorumV1BacktestTradeRead(
            id=trade.id,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=trade.exit_time,
            exit_price=trade.exit_price,
            tp_price=trade.tp_price,
            volume=trade.volume,
            multiplier=trade.multiplier,
            support_level=trade.support_level,
            support_zone_id=trade.support_zone_id,
            operation_zone_id=trade.operation_zone_id,
            pullback_pct=trade.pullback_pct,
            pullback_low=trade.pullback_low,
            pullback_low_time=trade.pullback_low_time,
            exit_reason=trade.exit_reason,
            status="CLOSED" if trade.status == "CLOSED" else "OPEN",
            bars_held=trade.bars_held,
            gross_profit=round(trade.gross_profit, 8),
            commission=round(trade.commission, 8),
            net_profit=round(trade.net_profit, 8),
            return_pct=round(trade.return_pct, 6),
            mfe_pct=round(trade.mfe_pct, 6),
            mae_pct=round(trade.mae_pct, 6),
            balance_before=round(trade.balance_before, 8),
            balance_after=round(trade.balance_after, 8) if trade.balance_after is not None else None,
            risk_at_entry=round(trade.risk_at_entry, 8) if trade.risk_at_entry is not None else None,
            ath_zone=trade.ath_zone,
        )

    def _metrics(
        self,
        *,
        request: TorumV1BacktestRequest,
        trades: list[_OpenTrade],
        open_trades: list[_OpenTrade],
        initial_balance: float,
        final_balance: float,
        final_equity: float,
        max_drawdown: float,
        max_drawdown_pct: float,
        bars_with_exposure: int,
        candles_count: int,
        max_concurrent_trades: int,
        trading_days: int,
        signals_detected: int,
        blocked_signals: int,
        rejection_counts: dict[str, int],
    ) -> TorumV1BacktestMetricsRead:
        closed = [trade for trade in trades if trade.status == "CLOSED"]
        profits = [trade.net_profit for trade in closed]
        wins = [value for value in profits if value > 1e-9]
        losses = [value for value in profits if value < -1e-9]
        breakeven = len(profits) - len(wins) - len(losses)
        gross_profit = sum(max(0.0, trade.gross_profit) for trade in closed)
        gross_loss = sum(min(0.0, trade.gross_profit) for trade in closed)
        net_profit = sum(profits)
        consecutive_wins, consecutive_losses = _consecutive_streaks(profits)
        support_breakdown = _trade_breakdown(
            closed,
            lambda trade: f"S{trade.support_level}" if trade.support_level is not None else "SIN_SOPORTE",
        )
        zone_breakdown = _trade_breakdown(
            closed,
            lambda trade: trade.operation_zone_id or "SIN_ZONA",
        )
        average_win = sum(wins) / len(wins) if wins else 0.0
        average_loss = sum(losses) / len(losses) if losses else 0.0
        pullback_values = [trade.pullback_pct for trade in closed if trade.pullback_pct is not None]
        risk_values = [trade.risk_at_entry for trade in trades if trade.risk_at_entry is not None]
        return TorumV1BacktestMetricsRead(
            initial_balance=round(initial_balance, 8),
            final_balance=round(final_balance, 8),
            final_equity=round(final_equity, 8),
            net_profit=round(net_profit, 8),
            total_return_pct=round(net_profit / initial_balance * 100.0, 6) if initial_balance else 0.0,
            gross_profit=round(gross_profit, 8),
            gross_loss=round(gross_loss, 8),
            total_commission=round(sum(trade.commission for trade in closed), 8),
            total_trades=len(trades),
            closed_trades=len(closed),
            open_trades=len(open_trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=breakeven,
            win_rate_pct=round(len(wins) / len(closed) * 100.0, 4) if closed else 0.0,
            profit_factor=round(gross_profit / abs(gross_loss), 6) if gross_loss < 0 else None,
            payoff_ratio=round(average_win / abs(average_loss), 6) if average_win > 0 and average_loss < 0 else None,
            recovery_factor=round(net_profit / max_drawdown, 6) if max_drawdown > 0 else None,
            expectancy=round(net_profit / len(closed), 8) if closed else 0.0,
            average_trade=round(net_profit / len(closed), 8) if closed else 0.0,
            average_win=round(average_win, 8),
            average_loss=round(average_loss, 8),
            best_trade=round(max(profits), 8) if profits else 0.0,
            worst_trade=round(min(profits), 8) if profits else 0.0,
            max_drawdown=round(max_drawdown, 8),
            max_drawdown_pct=round(max_drawdown_pct, 6),
            max_consecutive_wins=consecutive_wins,
            max_consecutive_losses=consecutive_losses,
            average_bars_held=round(sum(trade.bars_held for trade in closed) / len(closed), 4) if closed else 0.0,
            exposure_pct=round(bars_with_exposure / candles_count * 100.0, 4) if candles_count else 0.0,
            max_concurrent_trades=max_concurrent_trades,
            trading_days=trading_days,
            trades_per_day=round(len(closed) / trading_days, 6) if trading_days else 0.0,
            average_pullback_pct=round(sum(pullback_values) / len(pullback_values), 6) if pullback_values else 0.0,
            average_risk_at_entry=round(sum(risk_values) / len(risk_values), 8) if risk_values else 0.0,
            average_mfe_pct=round(sum(trade.mfe_pct for trade in closed) / len(closed), 6) if closed else 0.0,
            average_mae_pct=round(sum(trade.mae_pct for trade in closed) / len(closed), 6) if closed else 0.0,
            signals_detected=signals_detected,
            blocked_signals=blocked_signals,
            rejection_counts=dict(sorted(rejection_counts.items(), key=lambda item: (-item[1], item[0]))),
            support_breakdown=support_breakdown,
            zone_breakdown=zone_breakdown,
        )

    def _debug(
        self,
        events: list[TorumV1BacktestDebugEventRead],
        request: TorumV1BacktestRequest,
        *,
        time_: datetime,
        candle_index: int,
        stage: str,
        status: str,
        reason_code: str,
        summary: str,
        price: float | None,
        details: dict[str, Any],
    ) -> None:
        if len(events) >= request.max_debug_events:
            return
        if request.debug_level == "SUMMARY" and status not in {"ENTRY", "EXIT"}:
            return
        if request.debug_level == "SIGNALS" and status == "REJECT" and stage == "technical" and reason_code in {
            "missing_pullback",
            "missing_current_pullback",
            "current_pullback_below_entry_min",
            "waiting_bullish_confirmation",
            "missing_closed_m5_candles",
        }:
            return
        events.append(
            TorumV1BacktestDebugEventRead(
                time=time_,
                candle_index=candle_index,
                stage=stage,
                status=status,  # type: ignore[arg-type]
                reason_code=reason_code,
                summary=summary,
                price=price,
                details=details,
            )
        )


_MADRID = __import__("zoneinfo").ZoneInfo("Europe/Madrid")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _session_allows(params: dict[str, Any], checked_at: datetime) -> bool:
    madrid = checked_at.astimezone(_MADRID)
    days = {
        str(item).upper()
        for item in params.get("session_days", ["MO", "TU", "WE", "TH", "FR"])
    }
    weekday = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[madrid.weekday()]
    if weekday not in days:
        return False
    try:
        start_hour, start_minute = map(int, str(params.get("session_start") or "00:00").split(":"))
        end_hour, end_minute = map(int, str(params.get("session_end") or "23:59").split(":"))
    except (TypeError, ValueError):
        return False
    current = madrid.hour * 60 + madrid.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return start <= current <= end if start <= end else current >= start or current <= end


def _news_blocks(zones: Iterable[NoTradeZone], checked_at: datetime) -> bool:
    return any(
        bool(zone.blocks_trading)
        and _utc(zone.start_time) <= checked_at <= _utc(zone.end_time)
        for zone in zones
    )


def _historical_dxy_decision(
    symbol: str,
    params: dict[str, Any],
    checked_at: datetime,
    points: list[_DxyPoint],
    times: list[datetime],
) -> dict[str, Any]:
    if not bool(params.get("usd_strength_filter_enabled", True)):
        return {"allowed": True, "reason": "usd_filter_disabled", "state": "DISABLED"}
    applies = {
        str(item).upper()
        for item in params.get("usd_strength_apply_to_symbols", ["XAUUSD", "XAUEUR"])
    }
    if symbol.upper() not in applies:
        return {"allowed": True, "reason": "usd_filter_not_applied", "state": "SKIP"}
    index = bisect_right(times, checked_at) - 1
    if index < 0 or points[index].sma is None:
        strict = bool(params.get("usd_strength_strict", False))
        return {
            "allowed": not strict,
            "reason": "usd_strength_unknown",
            "state": "UNKNOWN",
            "strict": strict,
        }
    point = points[index]
    band = float(params.get("usd_neutral_band_points", 0.10))
    difference = point.close - float(point.sma)
    state = "NEUTRAL"
    reason = "dxy_neutral_zone"
    override = False
    if difference < -band:
        state = "WEAK"
        reason = "dxy_below_sma30"
    elif difference > band:
        state = "STRONG"
        reason = "dxy_above_sma30"
        if bool(params.get("usd_strong_drop_override_enabled", True)) and point.close_n_days_ago:
            drop_pct = (point.close - point.close_n_days_ago) / point.close_n_days_ago * 100.0
            bearish_ok = (
                not bool(params.get("usd_strong_drop_require_bearish_close", True))
                or point.close < point.open
            )
            if drop_pct <= -float(params.get("usd_strong_drop_min_pct", 0.45)) and bearish_ok:
                state = "WEAK"
                reason = "dxy_above_sma30_but_falling_strongly"
                override = True
    mode = str(params.get("usd_strength_mode", "only_operate_when_weak"))
    if mode == "info_only":
        allowed = True
    elif mode == "block_when_strong":
        allowed = state != "STRONG"
    else:
        allowed = state == "WEAK" or (
            state == "NEUTRAL" and bool(params.get("usd_allow_when_neutral", False))
        )
    return {
        "allowed": allowed,
        "reason": reason,
        "state": state,
        "dxy": point.close,
        "sma": point.sma,
        "difference": difference,
        "strong_drop_override": override,
    }


def _decision_details(decision: Any) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if getattr(decision, "pullback", None) is not None:
        details.update(
            pullback_pct=decision.pullback.pullback_pct,
            pullback_low=decision.pullback.pullback_low,
            pullback_low_time=_utc(decision.pullback.pullback_low_time).isoformat(),
        )
    if getattr(decision, "zone", None) is not None:
        details["operation_zone_id"] = decision.zone.drawing_id
    if getattr(decision, "support", None) is not None:
        details["support_zone_id"] = decision.support.drawing_id
        details["support_level"] = decision.support.level
    metadata = getattr(decision, "metadata", None)
    if isinstance(metadata, dict):
        for key in (
            "confirmation_close",
            "executable_price",
            "confirmation_time_inside_operation_zone",
            "confirmation_price_inside_operation_zone",
            "confirmation_inside_operation_zone",
            "operation_zone_allow_confirmation_price_outside",
            "operation_zone_time1",
            "operation_zone_time2",
            "operation_zone_price_min",
            "operation_zone_price_max",
        ):
            if key in metadata:
                details[key] = metadata[key]
    return details


def _stage_for_reason(reason: str) -> str:
    if reason in {"outside_session", "outside_session_day"}:
        return "session"
    if reason == "news_zone":
        return "news"
    if reason.startswith("dxy_") or reason.startswith("usd_"):
        return "dxy"
    if reason in {
        "waiting_closed_candle",
        "missing_current_candle",
        "missing_previous_candle",
        "current_candle_not_bearish",
        "previous_candle_not_bearish",
        "broke_previous_low",
    }:
        return "unlock"
    if reason in {
        "risk_limit_exceeded",
        "ath_or_position_capacity_exceeded",
        "requested_multiplier_does_not_fit",
    }:
        return "risk"
    return "technical"



def _record_backtest_entry_cycle(
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    entry_price: float | None = None,
    prior_open_trades: list[_OpenTrade] | None = None,
) -> None:
    confirmation_time = _int_or_none(metadata.get("confirmation_candle_time"))
    if confirmation_time is None or confirmation_time <= 0:
        return
    raw = params.get("executed_entry_cycle_boundaries")
    boundaries = list(raw) if isinstance(raw, list) else []
    boundaries.append(confirmation_time)
    params["executed_entry_cycle_boundaries"] = sorted(
        {
            parsed
            for value in boundaries
            if (parsed := _int_or_none(value)) is not None and parsed > 0
        }
    )[-100:]
    params["last_executed_entry_candle_time"] = confirmation_time
    prior = list(prior_open_trades or [])
    params["executed_entry_price_ladder"] = update_torum_entry_price_ladder(
        params,
        executed_price=entry_price,
        order_id=None,
        confirmation_candle_time=confirmation_time,
        prior_open_positions=[
            SimpleNamespace(
                open_price=trade.entry_price,
                order_id=None,
                opened_at=trade.entry_time,
            )
            for trade in prior
        ],
        reset_campaign=not prior,
    )

def _reason_text(reason: str) -> str:
    labels = {
        "outside_session": "Fuera del horario permitido",
        "outside_session_day": "Día fuera de la sesión",
        "news_zone": "Bloqueado por una noticia activa",
        "waiting_closed_candle": "Esperando cierre H2/H3",
        "missing_current_candle": "Falta la vela H2/H3 actual",
        "missing_previous_candle": "Falta la vela H2/H3 anterior",
        "missing_unlock_day": "No hay cobertura histórica para el desbloqueo",
        "bullish_closed_candle": "Desbloqueado por vela alcista",
        "doji_closed_candle": "Desbloqueado por vela doji",
        "held_previous_low": "Desbloqueado: dos bajistas sin perder el mínimo",
        "current_candle_not_bearish": "La vela de desbloqueo no cumple",
        "previous_candle_not_bearish": "La vela anterior no es bajista",
        "broke_previous_low": "La vela bajista perdió el mínimo anterior",
        "waiting_bullish_confirmation": "Esperando vela alcista M5",
        "missing_pullback": "Esperando pullback válido",
        "missing_current_pullback": "La vela actual no confirma un pullback",
        "current_pullback_below_entry_min": "El pullback actual no alcanza el mínimo de entrada",
        "pullback_low_outside_operation_zone": "El mínimo del pullback está fuera de la zona",
        "confirmation_time_outside_operation_zone": "La confirmación quedó fuera del intervalo temporal del rectángulo operativo",
        "confirmation_price_outside_operation_zone": "La confirmación o el precio de entrada está fuera del rango vertical del rectángulo operativo",
        "third_entry_price_too_close": "Hay dos posiciones abiertas demasiado próximas y la nueva entrada sigue en la misma zona de precio",
        "entry_time_outside_operation_zone": "El momento real simulado de entrada quedó fuera del intervalo temporal del rectángulo",
        "entry_price_outside_operation_zone": "El precio real simulado de entrada quedó fuera del rango vertical del rectángulo",
        "duplicate_signal_pullback": "El pullback ya fue utilizado",
        "open_position_exists": "Ya existe una posición abierta",
        "usd_strength_strong": "Dólar fuerte: no se permite operar",
        "usd_strength_unknown": "No hay DXY histórico suficiente",
        "dxy_above_sma30": "DXY sobre SMA: dólar fuerte",
        "dxy_below_sma30": "DXY bajo SMA: dólar débil",
        "dxy_neutral_zone": "DXY en zona neutral",
        "dxy_above_sma30_but_falling_strongly": "DXY sobre SMA pero cayendo con fuerza",
        "ath_or_position_capacity_exceeded": "Sin capacidad por ATH o máximo de entradas",
        "requested_multiplier_does_not_fit": "El multiplicador solicitado no cabe",
        "risk_limit_exceeded": "La pérdida potencial supera el límite",
        "buy_pullback_confirmed_inside_zone": "Setup técnico válido",
        "buy_pullback_inside_zone_confirmation_price_outside_allowed": "Setup válido: pullback y tiempo dentro; salida por precio permitida",
    }
    return labels.get(reason, reason.replace("_", " "))


def _consecutive_streaks(profits: list[float]) -> tuple[int, int]:
    best_wins = 0
    best_losses = 0
    current_wins = 0
    current_losses = 0
    for value in profits:
        if value > 0:
            current_wins += 1
            current_losses = 0
        elif value < 0:
            current_losses += 1
            current_wins = 0
        else:
            current_wins = 0
            current_losses = 0
        best_wins = max(best_wins, current_wins)
        best_losses = max(best_losses, current_losses)
    return best_wins, best_losses


def _trade_breakdown(
    trades: list[_OpenTrade],
    key_fn: Any,
) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for trade in trades:
        key = str(key_fn(trade))
        row = result.setdefault(key, {"trades": 0, "wins": 0, "net_profit": 0.0})
        row["trades"] = int(row["trades"]) + 1
        if trade.net_profit > 0:
            row["wins"] = int(row["wins"]) + 1
        row["net_profit"] = round(float(row["net_profit"]) + trade.net_profit, 8)
    return result


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _timestamp_or_none(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(raw, UTC) if raw > 0 else None

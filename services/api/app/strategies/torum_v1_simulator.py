from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_context.dollar_strength import DollarStrengthService, usd_strength_decision_for_symbol
from app.no_trade_zones.models import NoTradeZone
from app.risk.snapshot import RiskSnapshotService
from app.strategies.engine import StrategyContextBuilder
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings
from app.strategies.schemas import (
    StrategyTraceStep,
    TorumV1ReplayRead,
    TorumV1ReplaySignalRead,
    TorumV1SimulationRead,
)
from app.strategies.torum_v1 import (
    detect_pullbacks,
    is_bullish_confirmation,
    is_price_inside_operation_zone,
    is_pullback_low_inside_operation_zone,
    is_time_inside_operation_zone,
    operation_zones_from_drawings,
    should_buy_torum_v1,
    support_zones_from_drawings,
    TorumV1StatusService,
)
from app.strategies.torum_v1_config import TorumV1Params


class TorumV1Simulator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def simulate(
        self,
        config: StrategyConfig,
        *,
        params_override: dict[str, Any] | None = None,
        candle_limit: int = 600,
    ) -> TorumV1SimulationRead:
        evaluated_at = datetime.now(UTC)
        params = TorumV1Params.normalize(
            config.internal_symbol,
            {**(config.params_json or {}), **(params_override or {})},
        ).model_dump()
        context = StrategyContextBuilder(self.db).build(config, limit=candle_limit)
        context.params = params
        current_price = context.latest_price
        steps: list[StrategyTraceStep] = []

        global_settings = get_global_strategy_settings(self.db)
        engine_ok = bool(global_settings.strategies_enabled)
        config_ok = bool(config.enabled and params.get("enabled", True))
        steps.append(
            _step(
                "engine",
                "Motor y activo",
                "PASS" if engine_ok and config_ok else "FAIL",
                "Motor y configuración activos" if engine_ok and config_ok else "Motor global o activo desactivado",
                actual={"engine": engine_ok, "asset": config_ok},
                required=True,
            )
        )

        asset_status = TorumV1StatusService(self.db).asset_status(
            config.internal_symbol,
            config,
            global_settings.strategies_enabled,
            evaluated_at,
        )
        session_status = "PASS" if asset_status.reason != "outside_session" else "FAIL"
        unlock_status = "PASS" if asset_status.status == "UNLOCKED" else "WAIT"
        if asset_status.blocked_by_news:
            unlock_status = "SKIP"
        steps.append(
            _step(
                "session",
                "Horario",
                session_status,
                f"{asset_status.session_start}-{asset_status.session_end}" if session_status == "PASS" else "Fuera del horario permitido",
                actual=evaluated_at.isoformat(),
                required={"start": asset_status.session_start, "end": asset_status.session_end},
            )
        )
        steps.append(
            _step(
                "news",
                "Noticias",
                "FAIL" if asset_status.blocked_by_news else "PASS",
                "Bloqueo activo por noticia" if asset_status.blocked_by_news else "Sin bloqueo de noticias",
                actual=asset_status.blocked_by_news,
                required=False,
            )
        )
        steps.append(
            _step(
                "unlock",
                "Desbloqueo H2/H3",
                unlock_status,
                _reason_text(asset_status.reason),
                actual=asset_status.reason,
                required="UNLOCKED",
            )
        )

        closed = [
            candle
            for candle in context.candles
            if _utc(candle.time) + timedelta(minutes=5) <= evaluated_at
        ]
        last_candle = closed[-1] if closed else None
        accept_doji_as_bullish = bool(params.get("confirmation_ignore_doji", True))
        confirmation_ok = bool(
            last_candle
            and (
                not params["confirmation_require_bullish"]
                or is_bullish_confirmation(last_candle, accept_doji_as_bullish=accept_doji_as_bullish)
            )
        )
        if confirmation_ok and params["confirmation_close_above_previous_high"] and len(closed) >= 2:
            confirmation_ok = float(last_candle.close) > float(closed[-2].high)
        steps.append(
            _step(
                "confirmation",
                "Confirmación M5",
                "PASS" if confirmation_ok else "WAIT",
                "Vela de confirmación cerrada" if confirmation_ok else "Esperando la vela de confirmación",
                actual={
                    "time": _utc(last_candle.time).isoformat() if last_candle else None,
                    "open": float(last_candle.open) if last_candle else None,
                    "close": float(last_candle.close) if last_candle else None,
                },
                required={"bullish": params["confirmation_require_bullish"]},
            )
        )

        cycle_boundaries = _entry_cycle_boundaries(params)
        cycle_closed = closed
        if cycle_boundaries:
            cycle_start = datetime.fromtimestamp(cycle_boundaries[-1], UTC)
            cycle_closed = [candle for candle in closed if _utc(candle.time) >= cycle_start]

        pullbacks = detect_pullbacks(
            cycle_closed,
            threshold=float(params["pullback_entry_min_pct"]),
            lookback=int(params["pullback_lookback_bars"]),
            recovery_pct=float(params.get("pullback_entry_recovery_pct", 0.0)),
            end_confirmation_bars=int(params["pullback_end_confirmation_bars"]),
            max_count=int(params["pullback_max_count"]),
            min_bars_between=int(params["pullback_min_bars_between"]),
            use_wicks=bool(params["pullback_use_wicks"]),
            use_close_confirmation=bool(params["pullback_use_close_confirmation"]),
            accept_doji_as_recovery=accept_doji_as_bullish,
            live_update_enabled=False,
            swing_confirm_bars=int(params["pullback_swing_confirm_bars"]),
            allow_peak_extension=bool(params["pullback_allow_peak_extension"]),
            require_bearish_leg=bool(params["pullback_require_bearish_leg"]),
            min_bearish_candles=int(params["pullback_min_bearish_candles"]),
            min_lower_close_candles=int(params["pullback_min_lower_close_candles"]),
            disallow_same_candle_peak_low=bool(params["pullback_disallow_same_candle_peak_low"]),
            impulse_green_filter_enabled=bool(params["pullback_impulse_green_filter_enabled"]),
        )
        confirmation_time = _utc(last_candle.time) if last_candle else None
        current_pullbacks = [
            item
            for item in pullbacks
            if not item.is_live and item.confirmation_candle_time == confirmation_time
        ]
        last_pullback = current_pullbacks[-1] if current_pullbacks else None
        pullback_meets_minimum = bool(
            last_pullback and last_pullback.pullback_pct >= float(params["pullback_entry_min_pct"])
        )
        steps.append(
            _step(
                "pullback",
                "Pullback",
                "PASS" if pullback_meets_minimum else "WAIT",
                (
                    f"Pullback actual {last_pullback.pullback_pct:.2f}%"
                    if pullback_meets_minimum and last_pullback
                    else f"Pullback actual {last_pullback.pullback_pct:.2f}%: inferior al mínimo"
                    if last_pullback
                    else "La vela actual no confirma un pullback"
                ),
                actual=round(last_pullback.pullback_pct, 4) if last_pullback else None,
                required=float(params["pullback_entry_min_pct"]),
                details={
                    "low": last_pullback.pullback_low if last_pullback else None,
                    "low_time": _utc(last_pullback.pullback_low_time).isoformat() if last_pullback else None,
                },
            )
        )

        operation_zones = operation_zones_from_drawings(context.manual_zones)
        price_tolerance_pct = float(params.get("operation_zone_price_tolerance_pct", 0.0) or 0.0)
        time_tolerance_minutes = int(params.get("operation_zone_time_tolerance_minutes", 0) or 0)
        pullback_matching_zones = []
        if last_pullback is not None:
            pullback_matching_zones = [
                zone
                for zone in operation_zones
                if is_pullback_low_inside_operation_zone(
                    last_pullback,
                    zone,
                    price_tolerance_pct=price_tolerance_pct,
                    time_tolerance_minutes=time_tolerance_minutes,
                )
            ]
        pullback_zone = pullback_matching_zones[0] if pullback_matching_zones else None
        confirmation_time_zone = None
        confirmation_zone = None
        executable_price = float(current_price) if current_price is not None else (
            float(last_candle.close) if last_candle is not None else None
        )
        if last_candle is not None and executable_price is not None:
            confirmation_close_at = _utc(last_candle.time) + timedelta(minutes=5)
            confirmation_time_zone = next(
                (
                    zone
                    for zone in pullback_matching_zones
                    if is_time_inside_operation_zone(
                        checked_at=confirmation_close_at,
                        zone=zone,
                        time_tolerance_minutes=time_tolerance_minutes,
                    )
                ),
                None,
            )
            confirmation_zone = next(
                (
                    zone
                    for zone in pullback_matching_zones
                    if is_time_inside_operation_zone(
                        checked_at=confirmation_close_at,
                        zone=zone,
                        time_tolerance_minutes=time_tolerance_minutes,
                    )
                    and is_price_inside_operation_zone(
                        price=executable_price,
                        zone=zone,
                        price_tolerance_pct=price_tolerance_pct,
                    )
                ),
                None,
            )
        allow_confirmation_price_outside = bool(
            params.get("operation_zone_allow_confirmation_price_outside", False)
        )
        matching_zone = confirmation_zone or (
            confirmation_time_zone if allow_confirmation_price_outside else None
        )
        zone_required = bool(params["require_zone"])
        zone_ok = not zone_required or matching_zone is not None
        if confirmation_zone is not None:
            zone_summary = "Pullback, tiempo de confirmación y precio de entrada dentro de la zona"
        elif confirmation_time_zone is not None and allow_confirmation_price_outside:
            zone_summary = "Pullback y tiempo dentro; salida por precio permitida en ajustes"
        elif confirmation_time_zone is not None:
            zone_summary = "El pullback y el tiempo cumplen, pero la confirmación o entrada está fuera por precio"
        elif pullback_zone is not None:
            zone_summary = "El pullback está dentro, pero la confirmación quedó fuera del intervalo temporal"
        elif not zone_required:
            zone_summary = "Zona no obligatoria"
        else:
            zone_summary = "El mínimo del pullback está fuera de las zonas"
        steps.append(
            _step(
                "zone",
                "Rectángulo operativo",
                "PASS" if zone_ok else "WAIT",
                zone_summary,
                actual={
                    "zone_id": (matching_zone or confirmation_time_zone or pullback_zone).drawing_id
                    if (matching_zone or confirmation_time_zone or pullback_zone)
                    else None,
                    "pullback_inside": pullback_zone is not None,
                    "confirmation_time_inside": confirmation_time_zone is not None,
                    "confirmation_price_inside": confirmation_zone is not None,
                    "entry_price": executable_price,
                },
                required={
                    "pullback_inside": zone_required,
                    "confirmation_time_inside": zone_required,
                    "confirmation_price_inside": zone_required and not allow_confirmation_price_outside,
                },
            )
        )


        usd_snapshot = DollarStrengthService(self.db).latest_snapshot_read()
        usd_decision = usd_strength_decision_for_symbol(config.internal_symbol, params, usd_snapshot)
        steps.append(
            _step(
                "usd",
                "Fortaleza del dólar",
                "PASS" if usd_decision.allowed else "FAIL",
                _reason_text(usd_decision.reason),
                actual=usd_decision.metadata,
                required="allowed",
            )
        )

        supports = support_zones_from_drawings(context.manual_zones)
        matched_support = None
        if last_pullback is not None:
            candidates = [item for item in supports if item.enabled and item.lower_price <= last_pullback.pullback_low <= item.upper_price]
            if candidates:
                matched_support = sorted(candidates, key=lambda item: (-item.level, abs(item.price - last_pullback.pullback_low)))[0]
        multiplier = int(params.get(f"support_s{matched_support.level}_multiplier", 1)) if matched_support else 1
        steps.append(
            _step(
                "support",
                "Soporte S1/S2/S3",
                "PASS" if matched_support else "SKIP",
                f"S{matched_support.level}, objetivo x{multiplier}" if matched_support else "Sin soporte: entrada simple",
                actual=matched_support.drawing_id if matched_support else None,
                required=None,
            )
        )

        risk_preview = RiskSnapshotService(self.db).preview_candidate(
            config.internal_symbol,
            side="BUY",
            volume=float(params["suggested_volume"]) * multiplier,
            price=current_price,
            source="STRATEGY",
        )
        risk_ok = bool(risk_preview.snapshot.valid and not risk_preview.breaches_limit)
        steps.append(
            _step(
                "risk",
                "Riesgo y ATH",
                "PASS" if risk_ok else ("WARN" if not risk_preview.snapshot.valid else "FAIL"),
                "Riesgo disponible" if risk_ok else (risk_preview.snapshot.message or "Límite de riesgo superado"),
                actual={
                    "candidate_loss": risk_preview.candidate_loss,
                    "projected_loss": risk_preview.projected_loss,
                    "projected_balance_pct": risk_preview.projected_balance_pct,
                    "remaining_risk": risk_preview.snapshot.remaining_risk,
                },
                required={"max_balance_pct": params["risk_max_balance_pct"]},
            )
        )

        technical = should_buy_torum_v1(
            symbol=config.internal_symbol,
            candles_m5=context.candles,
            operation_zones=operation_zones,
            support_zones=supports,
            params=params,
            now=evaluated_at,
            open_positions=context.open_positions,
            current_price=current_price,
        )

        blocking = [step for step in steps if step.status == "FAIL"]
        waiting = [step for step in steps if step.status == "WAIT"]
        if technical.should_buy and not blocking and risk_ok and asset_status.status == "UNLOCKED":
            decision = "BUY"
            reason = technical.reason
            summary = "Setup completo: la estrategia compraría ahora"
        elif blocking:
            decision = "BLOCKED"
            reason = str(blocking[0].id)
            summary = blocking[0].summary
        else:
            decision = "WAIT"
            reason = technical.reason if not technical.should_buy else (waiting[0].id if waiting else "waiting")
            summary = _reason_text(reason)

        return TorumV1SimulationRead(
            symbol=config.internal_symbol,
            evaluated_at=evaluated_at,
            decision=decision,
            reason_code=reason,
            summary=summary,
            current_price=current_price,
            steps=steps,
            metadata={
                "technical_decision": technical.reason,
                "technical_metadata": technical.metadata or {},
                "open_positions": len(context.open_positions),
                "candles": len(context.candles),
                "support_multiplier": multiplier,
            },
            config_revision=int(config.revision or 1),
        )

    def replay(
        self,
        config: StrategyConfig,
        *,
        params_override: dict[str, Any] | None = None,
        candle_limit: int = 500,
    ) -> TorumV1ReplayRead:
        """Replay the technical entry pipeline over historical M5 candles.

        This is deliberately side-effect free.  It evaluates session, news zones,
        pullback, operation zone, confirmation and support sizing.  Historical
        balance/risk and DXY state are not reconstructed because Torum does not
        persist account snapshots for every candle yet; those remain covered by
        the current-state simulator.
        """
        params = TorumV1Params.normalize(
            config.internal_symbol,
            {**(config.params_json or {}), **(params_override or {})},
        ).model_dump()
        for runtime_key in (
            "last_signal_candle_time",
            "last_signal_pullback_low_time",
            "last_signal_operation_zone_id",
            "last_executed_entry_candle_time",
            "last_executed_entry_order_id",
            "executed_entry_cycle_boundaries",
        ):
            params.pop(runtime_key, None)
        context = StrategyContextBuilder(self.db).build(config, limit=candle_limit)
        candles = sorted(context.candles, key=lambda item: _utc(item.time))
        operation_zones = operation_zones_from_drawings(context.manual_zones)
        supports = support_zones_from_drawings(context.manual_zones)
        signals: list[TorumV1ReplaySignalRead] = []
        seen: set[tuple[int, int]] = set()
        lookback_window = max(120, min(500, int(params.get("pullback_lookback_bars", 12)) * 12))
        historical_news_zones: list[NoTradeZone] = []
        if candles:
            historical_news_zones = list(
                self.db.scalars(
                    select(NoTradeZone).where(
                        NoTradeZone.internal_symbol == config.internal_symbol,
                        NoTradeZone.enabled.is_(True),
                        NoTradeZone.end_time >= _utc(candles[0].time),
                        NoTradeZone.start_time <= _utc(candles[-1].time) + timedelta(minutes=5),
                    )
                )
            )

        for index in range(2, len(candles)):
            confirmation = candles[index]
            confirmation_time = _utc(confirmation.time) + timedelta(minutes=5, seconds=1)
            if not _session_allows(params, confirmation_time):
                continue
            if bool(params.get("use_news", True)) and any(
                zone.blocks_trading
                and _utc(zone.start_time) <= confirmation_time <= _utc(zone.end_time)
                for zone in historical_news_zones
            ):
                continue
            window = candles[max(0, index - lookback_window + 1) : index + 1]
            decision = should_buy_torum_v1(
                symbol=config.internal_symbol,
                candles_m5=window,
                operation_zones=operation_zones,
                support_zones=supports,
                params=params,
                now=confirmation_time,
                open_positions=[],
                current_price=float(confirmation.close),
            )
            if not decision.should_buy or decision.metadata is None:
                continue
            confirmation_key = int(decision.metadata.get("confirmation_candle_time") or 0)
            pullback_key = int(decision.metadata.get("pullback_low_time") or 0)
            key = (confirmation_key, pullback_key)
            if key in seen:
                continue
            seen.add(key)
            pullback_low_time = (
                datetime.fromtimestamp(pullback_key, UTC) if pullback_key > 0 else None
            )
            signals.append(
                TorumV1ReplaySignalRead(
                    confirmation_time=datetime.fromtimestamp(confirmation_key, UTC)
                    if confirmation_key > 0
                    else _utc(confirmation.time),
                    price=float(confirmation.close),
                    pullback_pct=_float_or_none(decision.metadata.get("pullback_pct")),
                    pullback_low=_float_or_none(decision.metadata.get("pullback_low")),
                    pullback_low_time=pullback_low_time,
                    operation_zone_id=decision.metadata.get("operation_zone_id"),
                    support_level=_int_or_none(decision.metadata.get("support_level")),
                    desired_multiplier=max(1, _int_or_none(decision.metadata.get("desired_multiplier")) or 1),
                    reason=decision.reason,
                )
            )
            if confirmation_key > 0:
                _append_entry_cycle_boundary(params, confirmation_key)

        return TorumV1ReplayRead(
            symbol=config.internal_symbol,
            generated_at=datetime.now(UTC),
            from_time=_utc(candles[0].time) if candles else None,
            to_time=_utc(candles[-1].time) if candles else None,
            candles_analyzed=len(candles),
            signals=signals,
            signal_count=len(signals),
            coverage={
                "session": "historical",
                "news": "historical zones loaded in context",
                "pullback_zone_confirmation_support": "historical",
                "dxy": "use current-state simulator for full filter",
                "risk": "use current-state simulator; no historical account snapshots",
                "orders": "never executed",
            },
            notes=[
                "Replay técnico sin órdenes.",
                "No representa rentabilidad ni reconstruye balance/riesgo histórico.",
            ],
            config_revision=int(config.revision or 1),
        )



def _entry_cycle_boundaries(params: dict[str, Any]) -> list[int]:
    raw = params.get("executed_entry_cycle_boundaries")
    values = list(raw) if isinstance(raw, list) else []
    values.append(params.get("last_executed_entry_candle_time"))
    return sorted(
        {
            parsed
            for value in values
            if (parsed := _int_or_none(value)) is not None and parsed > 0
        }
    )


def _append_entry_cycle_boundary(params: dict[str, Any], confirmation_time: int) -> None:
    boundaries = _entry_cycle_boundaries(params)
    boundaries.append(confirmation_time)
    normalized = sorted(set(boundaries))[-100:]
    params["executed_entry_cycle_boundaries"] = normalized
    params["last_executed_entry_candle_time"] = confirmation_time

def _step(
    id_: str,
    label: str,
    status: str,
    summary: str,
    *,
    actual: Any = None,
    required: Any = None,
    details: dict[str, Any] | None = None,
) -> StrategyTraceStep:
    return StrategyTraceStep(
        id=id_,
        label=label,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        actual=actual,
        required=required,
        details=details or {},
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _session_allows(params: dict[str, Any], checked_at: datetime) -> bool:
    madrid = checked_at.astimezone(ZoneInfo("Europe/Madrid"))
    days = {str(item).upper() for item in params.get("session_days", ["MO", "TU", "WE", "TH", "FR"])}
    weekday = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[madrid.weekday()]
    if weekday not in days:
        return False
    try:
        start = time.fromisoformat(str(params.get("session_start") or "00:00"))
        end = time.fromisoformat(str(params.get("session_end") or "23:59"))
    except ValueError:
        return False
    current = madrid.time().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


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


def _reason_text(reason: str) -> str:
    labels = {
        "outside_session": "Fuera del horario permitido",
        "news_zone": "Bloqueado por una noticia activa",
        "waiting_closed_candle": "Esperando cierre H2/H3",
        "missing_current_candle": "Falta la vela actual",
        "missing_previous_candle": "Falta la vela anterior",
        "bullish_closed_candle": "Desbloqueado por vela alcista",
        "held_previous_low": "Desbloqueado: dos bajistas sin perder el mínimo",
        "waiting_bullish_confirmation": "Esperando vela alcista M5",
        "missing_pullback": "Esperando pullback válido",
        "missing_current_pullback": "La vela actual no confirma un pullback",
        "current_pullback_below_entry_min": "El pullback actual no alcanza el mínimo de entrada",
        "pullback_low_outside_operation_zone": "El mínimo del pullback está fuera de la zona",
        "confirmation_time_outside_operation_zone": "La confirmación quedó fuera del intervalo temporal del rectángulo operativo",
        "confirmation_price_outside_operation_zone": "La confirmación o el precio de entrada está fuera del rango vertical del rectángulo operativo",
        "usd_strength_strong": "Dólar fuerte: no se permite operar",
        "dxy_above_sma30": "DXY sobre SMA: dólar fuerte",
        "dxy_below_sma30": "DXY bajo SMA: dólar débil",
        "buy_pullback_confirmed_inside_zone": "Setup técnico válido",
        "buy_pullback_inside_zone_confirmation_price_outside_allowed": "Setup válido: pullback y tiempo dentro; salida por precio permitida",
    }
    return labels.get(str(reason), str(reason).replace("_", " "))

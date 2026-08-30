from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean
from threading import RLock
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.status_store import mt5_status_store
from app.positions.models import Position
from app.risk.schemas import GoldCorrelationRead, StopOutLineRead
from app.symbols.service import get_symbol_by_internal
from app.ticks.models import Tick
from app.ticks.service import latest_tick_order_by

_GOLD_SYMBOLS = ("XAUUSD", "XAUEUR")
_CORRELATION_TIMEFRAME = "H1"
_CORRELATION_LOOKBACK = 1000
_CORRELATION_MIN_SAMPLES = 120
_CORRELATION_MIN_USE = 0.80
_BETA_MIN = 0.35
_BETA_MAX = 1.65
_CALIBRATION_TTL_SECONDS = 60.0
_CALIBRATION_LOCK = RLock()
_CALIBRATION_CACHE: dict[tuple[int, str, str], tuple[float, float]] = {}


@dataclass(slots=True)
class _CorrelationModel:
    samples: int
    pearson: float | None
    beta_eur_from_usd: float
    beta_usd_from_eur: float
    source: str

    def to_read(self) -> GoldCorrelationRead:
        return GoldCorrelationRead(
            timeframe=_CORRELATION_TIMEFRAME,
            samples=self.samples,
            pearson=self.pearson,
            beta_xaueur_from_xauusd=self.beta_eur_from_usd,
            beta_xauusd_from_xaueur=self.beta_usd_from_eur,
            source=self.source,
        )


class StopOutLineService:
    """Estimate the first broker Stop Out trigger on the selected gold cross.

    Current account equity/margin are taken from MT5.  Only the selected gold
    symbol is moved directly; the other gold cross is moved by a rolling H1
    return beta when it also has open positions.  Other account exposures remain
    frozen inside current equity/margin.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_line(self, symbol: str) -> StopOutLineRead:
        target = symbol.upper()
        if target not in _GOLD_SYMBOLS:
            return self._empty(target, "La linea de Stop Out solo aplica a XAUUSD y XAUEUR.")

        status = mt5_status_store.get()
        account = status.account
        if not status.connected_to_mt5 or account is None or account.login is None:
            return self._empty(target, "MT5 no esta conectado a una cuenta.")

        positions = self._gold_positions(account.login, account.server)
        target_positions = [position for position in positions if position.internal_symbol == target]
        if not target_positions:
            return self._empty(target, "No hay posiciones abiertas en este activo.")

        equity = _positive_or_none(account.equity)
        margin = _positive_or_none(account.margin)
        stop_out = _nonnegative_or_none(getattr(account, "margin_so_so", None))
        stop_out_mode = _int_or_none(getattr(account, "margin_so_mode", None))
        if equity is None:
            return self._empty(target, "MT5 no informa del equity actual.")
        if stop_out is None or stop_out_mode not in {0, 1}:
            return self._empty(target, "MT5 no informa del nivel de Stop Out de esta cuenta.")

        if stop_out_mode == 0:
            if margin is None:
                return self._empty(target, "MT5 no informa del margen usado necesario para calcular el Stop Out.")
            threshold_equity = margin * stop_out / 100.0
            mode_label = "PERCENT"
        else:
            threshold_equity = stop_out
            mode_label = "MONEY"

        prices = {gold: self._current_close_price(gold, positions) for gold in _GOLD_SYMBOLS}
        current_target = prices.get(target)
        if current_target is None or current_target <= 0:
            return self._empty(target, f"No hay precio actual utilizable para {target}.")

        other = "XAUEUR" if target == "XAUUSD" else "XAUUSD"
        other_positions = [position for position in positions if position.internal_symbol == other]
        current_other = prices.get(other) if other_positions else None

        correlation = self._correlation_model()
        beta = (
            correlation.beta_eur_from_usd
            if target == "XAUUSD"
            else correlation.beta_usd_from_eur
        )
        use_correlated_leg = bool(other_positions and current_other is not None and current_other > 0)

        coefficients = {
            target: self._profit_per_price_unit(
                target,
                current_target,
                account_login=account.login,
                account_server=account.server or "",
            )
        }
        if use_correlated_leg:
            coefficients[other] = self._profit_per_price_unit(
                other,
                float(current_other),
                account_login=account.login,
                account_server=account.server or "",
            )

        if coefficients[target] <= 0 or (use_correlated_leg and coefficients.get(other, 0.0) <= 0):
            return self._empty(target, "No se pudo calibrar el beneficio/precio con el broker.")

        def scenario_other_price(target_price: float) -> float | None:
            if not use_correlated_leg or current_other is None:
                return None
            log_move = math.log(max(target_price, 1e-9) / current_target)
            return float(current_other) * math.exp(beta * log_move)

        def scenario_equity(target_price: float) -> float:
            scenario_prices = {target: target_price}
            other_price = scenario_other_price(target_price)
            if other_price is not None:
                scenario_prices[other] = other_price

            delta = 0.0
            for position in positions:
                scenario_price = scenario_prices.get(position.internal_symbol)
                current_price = prices.get(position.internal_symbol)
                coefficient = coefficients.get(position.internal_symbol)
                if scenario_price is None or current_price is None or coefficient is None:
                    continue
                direction = 1.0 if position.side.upper() == "BUY" else -1.0
                delta += (
                    (scenario_price - current_price)
                    * float(position.volume)
                    * coefficient
                    * direction
                )
            return equity + delta

        current_gap = scenario_equity(current_target) - threshold_equity
        if current_gap <= 0:
            stop_price = current_target
        else:
            low = max(current_target * 0.001, 1e-6)
            low_gap = scenario_equity(low) - threshold_equity
            if low_gap > 0:
                return StopOutLineRead(
                    symbol=target,
                    visible=False,
                    price=None,
                    account_currency=account.currency,
                    current_equity=equity,
                    current_margin=margin,
                    threshold_equity=threshold_equity,
                    stop_out_mode=mode_label,
                    stop_out_value=stop_out,
                    positions_on_symbol=len(target_positions),
                    gold_positions_total=len(positions),
                    correlated_other_symbol=other if use_correlated_leg else None,
                    projected_other_price=None,
                    correlation=correlation.to_read(),
                    estimated=True,
                    message="Incluso con una caida extrema del activo no se alcanza el Stop Out con las posiciones actuales.",
                )

            high = current_target
            for _ in range(64):
                mid = (low + high) / 2.0
                if scenario_equity(mid) <= threshold_equity:
                    low = mid
                else:
                    high = mid
            stop_price = high

        projected_other = scenario_other_price(stop_price)
        return StopOutLineRead(
            symbol=target,
            visible=True,
            price=round(stop_price, 5),
            account_currency=account.currency,
            current_equity=round(equity, 2),
            current_margin=round(margin, 2) if margin is not None else None,
            threshold_equity=round(threshold_equity, 2),
            stop_out_mode=mode_label,
            stop_out_value=stop_out,
            positions_on_symbol=len(target_positions),
            gold_positions_total=len(positions),
            correlated_other_symbol=other if use_correlated_leg else None,
            projected_other_price=round(projected_other, 5) if projected_other is not None else None,
            correlation=correlation.to_read(),
            estimated=True,
            message=(
                "Estimacion del primer Stop Out del broker. Usa equity/margen reales de MT5 "
                "y beta H1 del broker para la otra cotizacion de oro cuando ambas tienen posiciones."
            ),
        )

    def _empty(self, symbol: str, message: str) -> StopOutLineRead:
        return StopOutLineRead(
            symbol=symbol,
            visible=False,
            price=None,
            account_currency=None,
            current_equity=None,
            current_margin=None,
            threshold_equity=None,
            stop_out_mode=None,
            stop_out_value=None,
            positions_on_symbol=0,
            gold_positions_total=0,
            correlated_other_symbol=None,
            projected_other_price=None,
            correlation=self._correlation_model().to_read(),
            estimated=True,
            message=message,
        )

    def _gold_positions(self, account_login: int, account_server: str | None) -> list[Position]:
        stmt = select(Position).where(
            Position.internal_symbol.in_(_GOLD_SYMBOLS),
            Position.status == "OPEN",
            Position.closed_at.is_(None),
            Position.close_price.is_(None),
            Position.account_login == account_login,
        )
        if account_server:
            stmt = stmt.where(Position.account_server == account_server)
        return [
            position
            for position in self.db.scalars(stmt)
            if position.mode == "PAPER" or position.mt5_position_ticket is not None
        ]

    def _current_close_price(self, symbol: str, positions: list[Position]) -> float | None:
        tick = self.db.scalar(
            select(Tick)
            .where(Tick.internal_symbol == symbol)
            .order_by(*latest_tick_order_by())
            .limit(1)
        )
        if tick is not None:
            # All Torum gold positions are BUY today, but use BID as the
            # conservative executable mark for a downward Stop Out scenario.
            for value in (tick.bid, tick.last, tick.ask):
                parsed = _positive_or_none(value)
                if parsed is not None:
                    return parsed

        current_prices = [
            float(position.current_price)
            for position in positions
            if position.internal_symbol == symbol
            and position.current_price is not None
            and position.current_price > 0
        ]
        return fmean(current_prices) if current_prices else None

    def _profit_per_price_unit(
        self,
        symbol: str,
        current_price: float,
        *,
        account_login: int,
        account_server: str,
    ) -> float:
        key = (account_login, account_server, symbol)
        now = monotonic()
        with _CALIBRATION_LOCK:
            cached = _CALIBRATION_CACHE.get(key)
            if cached is not None and now - cached[0] < _CALIBRATION_TTL_SECONDS:
                return cached[1]

        mapping = get_symbol_by_internal(self.db, symbol)
        broker_symbol = mapping.broker_symbol if mapping is not None else symbol
        distance = max(current_price * 0.001, 0.01)
        close_price = max(current_price - distance, current_price * 0.5)
        coefficient: float | None = None
        try:
            response = MT5BridgeClient(timeout=2.0).calculate_profit(
                {
                    "broker_symbol": broker_symbol,
                    "side": "BUY",
                    "volume": 1.0,
                    "price_open": current_price,
                    "price_close": close_price,
                }
            )
            raw_profit = response.get("profit") if response.get("ok") else None
            if raw_profit is not None:
                coefficient = abs(float(raw_profit)) / abs(current_price - close_price)
        except (MT5BridgeClientError, TypeError, ValueError, ZeroDivisionError):
            coefficient = None

        if coefficient is None or not math.isfinite(coefficient) or coefficient <= 0:
            if mapping is None:
                return 0.0
            coefficient = float(mapping.contract_size or 0.0) * float(mapping.risk_conversion_rate or 1.0)

        with _CALIBRATION_LOCK:
            _CALIBRATION_CACHE[key] = (now, coefficient)
        return coefficient

    def _correlation_model(self) -> _CorrelationModel:
        usd = self._h1_closes("XAUUSD")
        eur = self._h1_closes("XAUEUR")
        common = sorted(set(usd).intersection(eur))
        usd_returns: list[float] = []
        eur_returns: list[float] = []
        for previous, current in zip(common, common[1:]):
            usd_prev, usd_now = usd[previous], usd[current]
            eur_prev, eur_now = eur[previous], eur[current]
            if min(usd_prev, usd_now, eur_prev, eur_now) <= 0:
                continue
            r_usd = math.log(usd_now / usd_prev)
            r_eur = math.log(eur_now / eur_prev)
            # Reject obvious feed gaps/outliers without smoothing real gold moves.
            if abs(r_usd) > 0.08 or abs(r_eur) > 0.08:
                continue
            usd_returns.append(r_usd)
            eur_returns.append(r_eur)

        samples = len(usd_returns)
        if samples < 2:
            return _CorrelationModel(samples, None, 1.0, 1.0, "FALLBACK_1_TO_1")

        pearson = _pearson(usd_returns, eur_returns)
        beta_eur = _ols_beta(usd_returns, eur_returns)
        beta_usd = _ols_beta(eur_returns, usd_returns)
        use_dynamic = (
            samples >= _CORRELATION_MIN_SAMPLES
            and pearson is not None
            and pearson >= _CORRELATION_MIN_USE
            and beta_eur is not None
            and beta_usd is not None
        )
        if not use_dynamic:
            return _CorrelationModel(samples, pearson, 1.0, 1.0, "FALLBACK_1_TO_1")

        return _CorrelationModel(
            samples,
            pearson,
            _clamp(beta_eur, _BETA_MIN, _BETA_MAX),
            _clamp(beta_usd, _BETA_MIN, _BETA_MAX),
            "BROKER_H1_LOG_RETURNS",
        )

    def _h1_closes(self, symbol: str) -> dict[object, float]:
        rows = list(
            self.db.scalars(
                select(Candle)
                .where(Candle.internal_symbol == symbol, Candle.timeframe == _CORRELATION_TIMEFRAME)
                .order_by(Candle.time.desc())
                .limit(_CORRELATION_LOOKBACK + 1)
            )
        )
        return {row.time: float(row.close) for row in rows if row.close > 0}


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    mean_x = fmean(x)
    mean_y = fmean(y)
    dx = [value - mean_x for value in x]
    dy = [value - mean_y for value in y]
    var_x = sum(value * value for value in dx)
    var_y = sum(value * value for value in dy)
    if var_x <= 0 or var_y <= 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(var_x * var_y)


def _ols_beta(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    mean_x = fmean(x)
    mean_y = fmean(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator <= 0:
        return None
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    return numerator / denominator


def _positive_or_none(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _nonnegative_or_none(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))

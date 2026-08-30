from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.mt5.schemas import MT5AccountPayload
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.performance.models import CapitalMovement
from app.performance.schemas import (
    CapitalMovementCreate,
    CapitalMovementRead,
    DailyPerformance,
    DailyTradePerformance,
    MonthlyPerformance,
    PerformanceBreakdown,
    PerformancePoint,
    PerformanceSummary,
)
from app.positions.models import Position
from app.settings.trading_service import get_global_trading_settings
from app.strategies.models import StrategySignal
from app.trading.lot_sizing import calculate_lot_size
from app.users.models import User, UserRole

_MADRID = ZoneInfo("Europe/Madrid")
_EPSILON = 1e-9


@dataclass(frozen=True)
class _ProfitEvent:
    time: datetime
    amount: float | None
    position_id: int
    symbol: str
    multiplier: int
    volume: float
    side: str
    opened_at: datetime
    open_price: float
    close_price: float | None


@dataclass(frozen=True)
class _CashEvent:
    time: datetime
    amount: float
    movement_id: int
    kind: str


@dataclass(frozen=True)
class _AccountScope:
    login: int | None
    server: str | None
    currency: str
    current_balance: float | None
    mode: str | None


class PerformanceService:
    """Account realized performance with cash-flow-neutral percentage returns.

    Percentage performance is time-weighted over finalized closed-trade P/L events.
    External deposits, withdrawals and MT5 balance adjustments change the
    capital base but contribute zero return, so adding money cannot inflate the
    displayed strategy percentage.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_manual_movement(self, user: User, payload: CapitalMovementCreate) -> CapitalMovement:
        scope = self._account_scope(user)
        occurred_at = _as_utc(payload.occurred_at)
        amount = float(payload.amount)

        # Capital inicial is a baseline, not an accumulating event. Editing it
        # should replace the user's previous manual baseline instead of silently
        # doubling the capital base.
        if payload.kind == "INITIAL":
            existing = self.db.scalar(
                select(CapitalMovement).where(
                    CapitalMovement.user_id == user.id,
                    CapitalMovement.source == "MANUAL",
                    CapitalMovement.kind == "INITIAL",
                    or_(CapitalMovement.account_login == scope.login, CapitalMovement.account_login.is_(None)),
                ).order_by(CapitalMovement.id).limit(1)
            )
            if existing is not None:
                existing.account_login = scope.login
                existing.account_server = scope.server
                existing.currency = scope.currency
                existing.occurred_at = occurred_at
                existing.amount = amount
                existing.note = (payload.note or "").strip() or None
                self.db.commit()
                self.db.refresh(existing)
                return existing

        # MT5 balance deals are imported automatically. Reject an accidental
        # manual duplicate close in time and amount; ADJUSTMENT remains
        # available when the user intentionally needs to correct the ledger.
        if payload.kind in {"DEPOSIT", "WITHDRAWAL"} and scope.login is not None:
            tolerance = timedelta(minutes=15)
            candidates = self.db.scalars(
                select(CapitalMovement).where(
                    CapitalMovement.source == "MT5",
                    CapitalMovement.account_login == scope.login,
                    CapitalMovement.occurred_at >= occurred_at - tolerance,
                    CapitalMovement.occurred_at <= occurred_at + tolerance,
                )
            )
            if any(abs(float(item.amount) - amount) < 0.005 for item in candidates):
                raise ValueError("Ese movimiento ya fue detectado automáticamente por MT5. Usa Ajuste si necesitas corregirlo.")

        movement = CapitalMovement(
            user_id=user.id,
            account_login=scope.login,
            account_server=scope.server,
            currency=scope.currency,
            occurred_at=occurred_at,
            amount=amount,
            kind=payload.kind,
            source="MANUAL",
            note=(payload.note or "").strip() or None,
        )
        self.db.add(movement)
        self.db.commit()
        self.db.refresh(movement)
        return movement

    def delete_manual_movement(self, user: User, movement_id: int) -> bool:
        movement = self.db.get(CapitalMovement, movement_id)
        if movement is None:
            return False
        if user.role != UserRole.admin and movement.user_id != user.id:
            return False
        if movement.source != "MANUAL":
            return False
        self.db.delete(movement)
        self.db.commit()
        return True

    def list_movements(self, user: User, *, limit: int = 200) -> list[CapitalMovement]:
        scope = self._account_scope(user)
        stmt = self._movement_stmt(user, scope).order_by(CapitalMovement.occurred_at.desc(), CapitalMovement.id.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def sync_mt5_capital_flows(self, cash_flows: list[dict[str, Any]], account: MT5AccountPayload | None) -> int:
        if not cash_flows or account is None or account.login is None:
            return 0
        created = 0
        server = account.server or None
        for raw in cash_flows:
            ticket = _int_or_none(raw.get("ticket") or raw.get("deal"))
            if ticket is None:
                continue
            amount = _float_or_none(raw.get("profit"))
            if amount is None or abs(amount) <= _EPSILON:
                continue
            occurred_at = _deal_time(raw)
            if occurred_at is None:
                continue
            existing = self.db.scalar(
                select(CapitalMovement.id).where(
                    CapitalMovement.account_login == account.login,
                    CapitalMovement.account_server == server,
                    CapitalMovement.external_id == ticket,
                ).limit(1)
            )
            if existing is not None:
                continue
            kind = str(raw.get("cash_flow_kind") or ("DEPOSIT" if amount > 0 else "WITHDRAWAL")).upper()
            if kind not in {"INITIAL", "DEPOSIT", "WITHDRAWAL", "ADJUSTMENT"}:
                kind = "ADJUSTMENT"
            note = str(raw.get("comment") or raw.get("deal_type_name") or "MT5 balance movement").strip() or None

            # If the user entered the capital movement manually before MT5's
            # history sync saw the balance deal, promote that row to the MT5
            # event instead of recording the same injection twice.  Reconcile
            # only an unambiguous same-amount movement close in time.
            tolerance = timedelta(minutes=15)
            manual_matches = list(
                self.db.scalars(
                    select(CapitalMovement).where(
                        CapitalMovement.source == "MANUAL",
                        CapitalMovement.account_login == account.login,
                        or_(CapitalMovement.account_server == server, CapitalMovement.account_server.is_(None)),
                        CapitalMovement.occurred_at >= occurred_at - tolerance,
                        CapitalMovement.occurred_at <= occurred_at + tolerance,
                    )
                )
            )
            manual_matches = [item for item in manual_matches if abs(float(item.amount) - amount) < 0.005]
            if len(manual_matches) == 1:
                movement = manual_matches[0]
                movement.account_server = server
                movement.currency = account.currency
                movement.occurred_at = occurred_at
                movement.amount = amount
                movement.kind = kind
                movement.source = "MT5"
                movement.external_id = ticket
                movement.note = movement.note or note
                movement.raw_payload_json = raw
                created += 1
                continue

            try:
                with self.db.begin_nested():
                    self.db.add(
                        CapitalMovement(
                            user_id=None,
                            account_login=account.login,
                            account_server=server,
                            currency=account.currency,
                            occurred_at=occurred_at,
                            amount=amount,
                            kind=kind,
                            source="MT5",
                            external_id=ticket,
                            note=note,
                            raw_payload_json=raw,
                        )
                    )
                    self.db.flush()
            except IntegrityError:
                continue
            created += 1
        if created:
            self.db.commit()
        return created

    def report(self, user: User, *, from_time: datetime, to_time: datetime) -> PerformanceSummary:
        start = _as_utc(from_time)
        end = _as_utc(to_time)
        if end <= start:
            raise ValueError("to_time must be after from_time")

        scope = self._account_scope(user)
        movements = self._movement_events(user, scope)
        closed_events = self._profit_events(user, scope, movements)
        profits = [event for event in closed_events if event.amount is not None]
        calculation = self._calculate_window(start, end, profits, movements, scope.current_balance)

        months: list[MonthlyPerformance] = []
        cursor_local = start.astimezone(_MADRID).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_local = end.astimezone(_MADRID)
        while cursor_local <= end_local:
            next_local = _next_month(cursor_local)
            month_start = max(start, cursor_local.astimezone(UTC))
            month_end = min(end, next_local.astimezone(UTC) - timedelta(microseconds=1))
            if month_end >= month_start:
                month_calc = self._calculate_window(month_start, month_end, profits, movements, scope.current_balance)
                month_events = [event for event in closed_events if month_start <= event.time <= month_end]
                month_profits = [event for event in month_events if event.amount is not None]
                wins = sum(1 for event in month_profits if (event.amount or 0.0) > 0)
                losses = sum(1 for event in month_profits if (event.amount or 0.0) < 0)
                months.append(
                    MonthlyPerformance(
                        key=cursor_local.strftime("%Y-%m"),
                        label=_month_label(cursor_local),
                        from_time=month_start,
                        to_time=month_end,
                        return_pct=month_calc["return_pct"],
                        net_profit=month_calc["net_profit"],
                        cash_flow=month_calc["cash_flow"],
                        trades=len(month_events),
                        pending=sum(1 for event in month_events if event.amount is None),
                        wins=wins,
                        losses=losses,
                    )
                )
            cursor_local = next_local

        period_events = [event for event in closed_events if start <= event.time <= end]
        period_profits = [event for event in period_events if event.amount is not None]
        gross_profit = sum(float(event.amount) for event in period_profits if float(event.amount) > 0)
        gross_loss = sum(float(event.amount) for event in period_profits if float(event.amount) < 0)
        wins = sum(1 for event in period_profits if float(event.amount) > 0)
        losses = sum(1 for event in period_profits if float(event.amount) < 0)
        finalized_count = len(period_profits)
        best_month = max((month for month in months if month.return_pct is not None), key=lambda item: item.return_pct or -math.inf, default=None)

        days = self._daily_performance(start, end, period_events, profits, movements, scope.current_balance)
        active_days = [day for day in days if day.trades > day.pending]
        best_day = max((day for day in active_days if day.return_pct is not None), key=lambda item: item.return_pct or -math.inf, default=None)
        worst_day = min((day for day in active_days if day.return_pct is not None), key=lambda item: item.return_pct or math.inf, default=None)
        max_win_streak, max_loss_streak, current_streak_type, current_streak = _streaks(period_profits)

        movement_rows = [
            self._movement_read(movement, user)
            for movement in self.list_movements(user, limit=120)
            if _as_utc(movement.occurred_at) <= end
        ]

        return PerformanceSummary(
            from_time=start,
            to_time=end,
            currency=scope.currency,
            return_pct=calculation["return_pct"],
            net_profit=calculation["net_profit"],
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            cash_flow=calculation["cash_flow"],
            capital_start=calculation["capital_start"],
            capital_end=calculation["capital_end"],
            current_balance=scope.current_balance,
            reconciliation_difference=calculation["reconciliation_difference"],
            trades=len(period_events),
            wins=wins,
            losses=losses,
            win_rate_pct=(wins / finalized_count * 100.0) if finalized_count else None,
            max_drawdown_pct=calculation["max_drawdown_pct"],
            profit_factor=(gross_profit / abs(gross_loss)) if gross_loss < -_EPSILON else None,
            expectancy=(calculation["net_profit"] / finalized_count) if finalized_count else None,
            average_win=(gross_profit / wins) if wins else None,
            average_loss=(gross_loss / losses) if losses else None,
            best_trade=max((float(event.amount) for event in period_profits), default=None),
            worst_trade=min((float(event.amount) for event in period_profits), default=None),
            profitable_days=sum(1 for day in active_days if day.net_profit > _EPSILON),
            losing_days=sum(1 for day in active_days if day.net_profit < -_EPSILON),
            best_day_pct=best_day.return_pct if best_day else None,
            worst_day_pct=worst_day.return_pct if worst_day else None,
            best_day_profit=max((day.net_profit for day in active_days), default=None),
            worst_day_profit=min((day.net_profit for day in active_days), default=None),
            max_win_streak=max_win_streak,
            max_loss_streak=max_loss_streak,
            current_streak_type=current_streak_type,
            current_streak=current_streak,
            best_month_key=best_month.key if best_month else None,
            best_month_return_pct=best_month.return_pct if best_month else None,
            basis_source=calculation["basis_source"],
            basis_note=calculation["basis_note"],
            pending_trades=sum(1 for event in period_events if event.amount is None),
            points=calculation["points"],
            days=days,
            months=months,
            multiplier_breakdown=_breakdown(period_events, key=lambda event: f"x{event.multiplier}", labels={"x1": "Simple · x1", "x2": "Doble · x2", "x3": "Triple · x3"}, order=("x1", "x2", "x3")),
            symbol_breakdown=_breakdown(period_events, key=lambda event: event.symbol, labels={"XAUUSD": "XAUUSD", "XAUEUR": "XAUEUR"}, order=("XAUUSD", "XAUEUR")),
            capital_movements=movement_rows,
        )

    def _daily_performance(
        self,
        start: datetime,
        end: datetime,
        period_events: list[_ProfitEvent],
        all_profits: list[_ProfitEvent],
        movements: list[_CashEvent],
        current_balance: float | None,
    ) -> list[DailyPerformance]:
        grouped: dict[object, list[_ProfitEvent]] = defaultdict(list)
        for event in period_events:
            grouped[event.time.astimezone(_MADRID).date()].append(event)

        rows: list[DailyPerformance] = []
        for day_key in sorted(grouped):
            local_start = datetime.combine(day_key, datetime.min.time(), tzinfo=_MADRID)
            local_end = local_start + timedelta(days=1) - timedelta(microseconds=1)
            day_start = max(start, local_start.astimezone(UTC))
            day_end = min(end, local_end.astimezone(UTC))
            day_events = sorted(grouped[day_key], key=lambda event: (event.time, event.position_id))
            day_profits = [event for event in day_events if event.amount is not None]
            day_calc = self._calculate_window(day_start, day_end, all_profits, movements, current_balance)
            details = [
                DailyTradePerformance(
                    position_id=event.position_id,
                    symbol=event.symbol,
                    multiplier=event.multiplier,
                    volume=event.volume,
                    side=event.side,
                    opened_at=event.opened_at,
                    closed_at=event.time,
                    open_price=event.open_price,
                    close_price=event.close_price,
                    net_profit=float(event.amount) if event.amount is not None else None,
                    pending=event.amount is None,
                    duration_minutes=max(0.0, (event.time - event.opened_at).total_seconds() / 60.0),
                )
                for event in day_events
            ]
            rows.append(
                DailyPerformance(
                    date=day_key,
                    return_pct=day_calc["return_pct"],
                    net_profit=sum(float(event.amount) for event in day_profits),
                    trades=len(day_events),
                    pending=sum(1 for event in day_events if event.amount is None),
                    wins=sum(1 for event in day_profits if float(event.amount) > 0),
                    losses=sum(1 for event in day_profits if float(event.amount) < 0),
                    x1=sum(1 for event in day_events if event.multiplier == 1),
                    x2=sum(1 for event in day_events if event.multiplier == 2),
                    x3=sum(1 for event in day_events if event.multiplier == 3),
                    xauusd=sum(1 for event in day_events if event.symbol == "XAUUSD"),
                    xaueur=sum(1 for event in day_events if event.symbol == "XAUEUR"),
                    trades_detail=details,
                )
            )
        return rows

    def _account_scope(self, user: User) -> _AccountScope:
        status = mt5_status_store.get()
        account = status.account
        if account is not None and account.login is not None:
            mode = "LIVE" if account.trade_mode == "REAL" else "DEMO" if account.trade_mode == "DEMO" else None
            return _AccountScope(
                login=account.login,
                server=account.server,
                currency=(account.currency or "EUR").upper(),
                current_balance=_float_or_none(account.balance),
                mode=mode,
            )

        # When MT5 is temporarily disconnected, keep the last account scope
        # based on the newest position regardless of whether it was opened by
        # the bot, manually from Torum, or directly in MetaTrader.
        stmt = select(Position).order_by(Position.closed_at.desc().nullslast(), Position.opened_at.desc()).limit(1)
        if user.role != UserRole.admin:
            stmt = stmt.where(Position.user_id == user.id)
        position = self.db.scalar(stmt)
        if position is None:
            return _AccountScope(None, None, "EUR", None, None)
        return _AccountScope(
            login=position.account_login,
            server=position.account_server,
            currency="EUR",
            current_balance=None,
            mode=position.mode if position.mode in {"LIVE", "DEMO"} else None,
        )

    def _profit_events(self, user: User, scope: _AccountScope, movements: list[_CashEvent]) -> list[_ProfitEvent]:
        """Return every closed trade visible in History for the active account.

        Strategy-only filtering used here previously caused Performance to omit
        manual Torum orders and trades opened directly in MT5.  The account
        history is the source of truth: every CLOSED position contributes to
        the calendar, while only fully enriched rows contribute monetary P/L.
        """

        stmt = (
            select(Position, Order, StrategySignal)
            .outerjoin(Order, Order.id == Position.order_id)
            .outerjoin(StrategySignal, StrategySignal.id == Order.strategy_signal_id)
            .where(
                Position.status == "CLOSED",
                Position.closed_at.is_not(None),
            )
            .order_by(Position.closed_at, Position.id)
        )
        if user.role != UserRole.admin:
            stmt = stmt.where(Position.user_id == user.id)

        # Match the History page exactly when an MT5 account is active.  Do not
        # leak legacy/null-account rows from another account into percentages.
        if scope.login is not None:
            stmt = stmt.where(Position.account_login == scope.login)
        if scope.server:
            stmt = stmt.where(Position.account_server == scope.server)

        trading_settings = get_global_trading_settings(self.db)
        prepared: list[tuple[Position, Order | None, StrategySignal | None, datetime, datetime, float | None]] = []
        for position, order, signal in self.db.execute(stmt):
            closed_at = _position_real_time(position.closed_at, position.mode)
            opened_at = _position_real_time(position.opened_at, position.mode)
            if closed_at is None or opened_at is None:
                continue
            net = position.net_profit
            pending = (
                position.profit is None
                or net is None
                or "PENDING" in str(position.enrichment_status or "").upper()
            )
            prepared.append((position, order, signal, opened_at, closed_at, None if pending else float(net)))

        # Current MT5 balance is authoritative. Walk backwards to each opening
        # instant so legacy/manual MT5 volumes are compared against the same
        # base-lot rule that Torum used at that time rather than today's balance.
        finalized_closes = [(closed_at, amount) for _, _, _, _, closed_at, amount in prepared if amount is not None]

        events: list[_ProfitEvent] = []
        for position, order, signal, opened_at, closed_at, net in prepared:
            historical_balance = scope.current_balance
            if historical_balance is not None:
                historical_balance -= sum(amount for event_time, amount in finalized_closes if event_time >= opened_at)
                historical_balance -= sum(movement.amount for movement in movements if movement.time > opened_at)

            base_lot = calculate_lot_size(
                available_equity=historical_balance,
                equity_per_0_01_lot=trading_settings.equity_per_0_01_lot,
                minimum_lot=trading_settings.minimum_lot,
                multiplier=1,
                enabled=trading_settings.lot_per_equity_enabled,
            ).base_lot
            multiplier = _trade_multiplier(
                position=position,
                order=order,
                signal=signal,
                base_lot=base_lot,
            )

            events.append(
                _ProfitEvent(
                    time=closed_at,
                    amount=net,
                    position_id=position.id,
                    symbol=str(position.internal_symbol or (order.internal_symbol if order is not None else "")).upper(),
                    multiplier=multiplier,
                    volume=float(position.volume),
                    side=str(position.side or "BUY").upper(),
                    opened_at=opened_at,
                    open_price=float(position.open_price),
                    close_price=_float_or_none(position.close_price),
                )
            )
        return events

    def _movement_stmt(self, user: User, scope: _AccountScope):
        # Manual ledgers are account-scoped when an MT5 account is known. This
        # prevents an old account's deposits/initial capital from contaminating
        # the percentage after the user connects a different trading account.
        manual_filters = [CapitalMovement.user_id == user.id]
        if scope.login is not None:
            manual_filters.append(
                or_(CapitalMovement.account_login == scope.login, CapitalMovement.account_login.is_(None))
            )
            if scope.server:
                manual_filters.append(
                    or_(CapitalMovement.account_server == scope.server, CapitalMovement.account_server.is_(None))
                )
        ownership = [and_(*manual_filters)]
        if scope.login is not None:
            account_filters = [CapitalMovement.account_login == scope.login]
            if scope.server:
                account_filters.append(CapitalMovement.account_server == scope.server)
            ownership.append(and_(CapitalMovement.source == "MT5", *account_filters))
        return select(CapitalMovement).where(or_(*ownership))

    def _movement_events(self, user: User, scope: _AccountScope) -> list[_CashEvent]:
        stmt = self._movement_stmt(user, scope).order_by(CapitalMovement.occurred_at, CapitalMovement.id)
        return [
            _CashEvent(_as_utc(movement.occurred_at), float(movement.amount), movement.id, movement.kind)
            for movement in self.db.scalars(stmt)
        ]

    def _calculate_window(
        self,
        start: datetime,
        end: datetime,
        profits: list[_ProfitEvent],
        movements: list[_CashEvent],
        current_balance: float | None,
    ) -> dict[str, Any]:
        initial_movements = [movement for movement in movements if movement.kind == "INITIAL" and movement.time <= end]

        if initial_movements:
            first_initial = min(initial_movements, key=lambda event: event.time)
            capital = 0.0
            if first_initial.time <= start:
                for event in _merged_events(
                    [profit for profit in profits if first_initial.time <= profit.time < start],
                    [movement for movement in movements if first_initial.time <= movement.time <= start],
                ):
                    capital += event[2]
            # If the selected range begins before the account was funded, start
            # from zero and let the INITIAL movement fund the TWR chain inside
            # the window. This keeps all-time/year views valid even when there
            # was no capital at the beginning of the selected dates.
            basis_source = "EXPLICIT_LEDGER"
            basis_note = "Porcentaje TWR calculado desde tu capital inicial y movimientos registrados; las aportaciones no cuentan como beneficio."
        elif current_balance is not None:
            # Anchor at current MT5 balance and walk backwards. This gives an
            # immediately useful return even before the user records an initial
            # capital event. Deposits imported from MT5 are explicitly removed.
            anchor = datetime.now(UTC)
            after_start_profit = sum(event.amount for event in profits if start <= event.time <= anchor)
            after_start_cash = sum(event.amount for event in movements if start < event.time <= anchor)
            capital = float(current_balance) - after_start_profit - after_start_cash
            basis_source = "MT5_BALANCE_BACKSOLVE"
            basis_note = "Base reconstruida desde el balance MT5 actual, beneficios Torum y aportaciones detectadas. Registra un capital inicial si quieres fijar una base histórica explícita."
        else:
            capital = math.nan
            basis_source = "UNAVAILABLE"
            basis_note = "Falta una base de capital. Añade un movimiento de Capital inicial para calcular el porcentaje; el beneficio en dinero sí es válido."

        capital_start = capital if math.isfinite(capital) else None
        cash_flow = 0.0
        net_profit = 0.0
        factor = 1.0
        return_base_available = bool(capital_start is not None and capital_start > _EPSILON)
        peak_factor = 1.0
        max_drawdown = 0.0
        cumulative_profit = 0.0
        points: list[PerformancePoint] = []

        grouped: dict[datetime, dict[str, float]] = defaultdict(lambda: {"cash": 0.0, "profit": 0.0})
        for movement in movements:
            if start < movement.time <= end:
                grouped[movement.time]["cash"] += movement.amount
        for profit in profits:
            if start <= profit.time <= end:
                grouped[profit.time]["profit"] += profit.amount

        for event_time in sorted(grouped):
            values = grouped[event_time]
            flow = values["cash"]
            pnl = values["profit"]
            if math.isfinite(capital):
                capital += flow
                if capital > _EPSILON:
                    return_base_available = True
            cash_flow += flow
            if abs(pnl) > _EPSILON:
                if math.isfinite(capital) and capital > _EPSILON:
                    sub_return = pnl / capital
                    factor *= 1.0 + sub_return
                    peak_factor = max(peak_factor, factor)
                    if peak_factor > _EPSILON:
                        max_drawdown = min(max_drawdown, factor / peak_factor - 1.0)
                if math.isfinite(capital):
                    capital += pnl
                net_profit += pnl
                cumulative_profit += pnl
            if abs(flow) > _EPSILON or abs(pnl) > _EPSILON:
                points.append(
                    PerformancePoint(
                        time=event_time,
                        return_pct=(factor - 1.0) * 100.0,
                        cumulative_profit=cumulative_profit,
                        capital=capital if math.isfinite(capital) else None,
                    )
                )

        return_pct = (factor - 1.0) * 100.0 if return_base_available else None
        capital_end = capital if math.isfinite(capital) else None
        reconciliation_difference = None
        now = datetime.now(UTC)
        if current_balance is not None and end >= now - timedelta(minutes=10) and capital_end is not None:
            reconciliation_difference = float(current_balance) - capital_end

        if not points:
            points = [
                PerformancePoint(time=start, return_pct=0.0, cumulative_profit=0.0, capital=capital_start),
                PerformancePoint(time=end, return_pct=0.0, cumulative_profit=0.0, capital=capital_end),
            ]
        elif points[0].time > start:
            points.insert(0, PerformancePoint(time=start, return_pct=0.0, cumulative_profit=0.0, capital=capital_start))

        return {
            "return_pct": return_pct,
            "net_profit": net_profit,
            "cash_flow": cash_flow,
            "capital_start": capital_start,
            "capital_end": capital_end,
            "reconciliation_difference": reconciliation_difference,
            "max_drawdown_pct": max_drawdown * 100.0 if return_pct is not None else None,
            "basis_source": basis_source,
            "basis_note": basis_note,
            "points": points,
        }

    @staticmethod
    def _movement_read(movement: CapitalMovement, user: User) -> CapitalMovementRead:
        return CapitalMovementRead(
            id=movement.id,
            occurred_at=movement.occurred_at,
            amount=float(movement.amount),
            kind=movement.kind,
            source=movement.source,
            currency=movement.currency,
            account_login=movement.account_login,
            account_server=movement.account_server,
            note=movement.note,
            external_id=movement.external_id,
            deletable=movement.source == "MANUAL" and (user.role == UserRole.admin or movement.user_id == user.id),
        )


def _merged_events(profits: Iterable[_ProfitEvent], movements: Iterable[_CashEvent]) -> list[tuple[datetime, int, float]]:
    # Cash first at equal timestamps so newly injected capital is available to
    # the subsequent realized P/L without being counted as strategy return.
    merged = [(movement.time, 0, movement.amount) for movement in movements]
    merged.extend((profit.time, 1, profit.amount) for profit in profits)
    merged.sort(key=lambda item: (item[0], item[1]))
    return merged


def _breakdown(
    events: list[_ProfitEvent],
    *,
    key: Any,
    labels: dict[str, str],
    order: tuple[str, ...],
) -> list[PerformanceBreakdown]:
    rows: list[PerformanceBreakdown] = []
    for item_key in order:
        grouped = [event for event in events if key(event) == item_key]
        finalized = [event for event in grouped if event.amount is not None]
        wins = sum(1 for event in finalized if float(event.amount) > 0)
        losses = sum(1 for event in finalized if float(event.amount) < 0)
        net = sum(float(event.amount) for event in finalized)
        rows.append(
            PerformanceBreakdown(
                key=item_key,
                label=labels.get(item_key, item_key),
                trades=len(grouped),
                pending=len(grouped) - len(finalized),
                wins=wins,
                losses=losses,
                win_rate_pct=(wins / len(finalized) * 100.0) if finalized else None,
                net_profit=net,
                average_profit=(net / len(finalized)) if finalized else 0.0,
            )
        )
    return rows


def _streaks(events: list[_ProfitEvent]) -> tuple[int, int, str | None, int]:
    max_wins = 0
    max_losses = 0
    current_type: str | None = None
    current = 0
    for event in events:
        if event.amount is None:
            continue
        event_type = "WIN" if float(event.amount) > 0 else "LOSS" if float(event.amount) < 0 else None
        if event_type is None:
            continue
        if event_type == current_type:
            current += 1
        else:
            current_type = event_type
            current = 1
        if event_type == "WIN":
            max_wins = max(max_wins, current)
        else:
            max_losses = max(max_losses, current)
    return max_wins, max_losses, current_type, current


def _trade_multiplier(
    *,
    position: Position,
    order: Order | None,
    signal: StrategySignal | None,
    base_lot: float,
) -> int:
    """Resolve x1/x2/x3 without discarding non-strategy history.

    Automatic Torum orders carry the exact accepted multiplier.  New manual
    Torum orders persist the selected multiplier in their request payload.  Old
    manual/external MT5 trades fall back to their volume relative to the
    account's current base lot, which is the same lot-equivalent convention
    used by the live capacity manager.
    """

    metadata = signal.metadata_json if signal is not None and isinstance(signal.metadata_json, dict) else {}
    explicit = _int_or_none(metadata.get("accepted_multiplier")) or _int_or_none(metadata.get("desired_multiplier"))
    if explicit is None and order is not None and isinstance(order.request_payload_json, dict):
        explicit = _int_or_none(order.request_payload_json.get("multiplier"))
    if explicit is not None:
        return max(1, min(3, explicit))

    safe_base = base_lot if base_lot > _EPSILON else 0.01
    ratio = max(0.0, float(position.volume)) / safe_base
    inferred = int(round(ratio)) if ratio > 0 else 1
    return max(1, min(3, inferred))


def _position_real_time(value: datetime | None, mode: str | None) -> datetime | None:
    """Convert live MT5 broker wall-clock timestamps to a real UTC instant.

    Torum intentionally stores MT5 chart/history timestamps as broker wall
    clock with a UTC tag so chart markers line up with broker candles.  That
    representation must not be used directly for calendar/TWR accounting.
    PAPER positions already use canonical UTC and are left untouched.
    """

    if value is None:
        return None
    observed = _as_utc(value)
    if str(mode or "").upper() == "PAPER":
        return observed
    try:
        broker_zone = ZoneInfo(get_settings().chart_broker_time_zone)
    except Exception:
        broker_zone = ZoneInfo("Etc/GMT-3")
    broker_wall = observed.replace(tzinfo=None).replace(tzinfo=broker_zone)
    return broker_wall.astimezone(UTC)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


def _month_label(value: datetime) -> str:
    names = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
    return f"{names[value.month - 1]} {value.year}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _deal_time(raw: dict[str, Any]) -> datetime | None:
    time_msc = _int_or_none(raw.get("time_msc"))
    if time_msc is not None and time_msc > 0:
        observed = datetime.fromtimestamp(time_msc / 1000.0, UTC)
    else:
        seconds = _float_or_none(raw.get("time"))
        if seconds is None or seconds <= 0:
            return None
        observed = datetime.fromtimestamp(seconds, UTC)

    # Live MT5 history in Torum uses the broker's wall clock while retaining a
    # UTC tz tag.  Cash-flow dates, unlike chart markers, must be real instants
    # so deposits/withdrawals land in the correct TWR period.
    if str(raw.get("time_domain") or "").upper() == "BROKER_CHART":
        try:
            broker_zone = ZoneInfo(get_settings().chart_broker_time_zone)
        except Exception:
            broker_zone = ZoneInfo("Etc/GMT-3")
        broker_wall = observed.replace(tzinfo=None).replace(tzinfo=broker_zone)
        return broker_wall.astimezone(UTC)
    return observed


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

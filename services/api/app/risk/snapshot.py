from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.positions.models import Position
from app.risk.schemas import RiskCandidatePreviewRead, RiskPositionExposureRead, RiskSnapshotRead
from app.strategies.ath import ATH_RISK_LIMIT_RATIO, get_or_update_symbol_ath
from app.symbols.service import get_symbol_by_internal

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskSnapshot:
    symbol: str
    mode: str = "ALL"
    source: str = "ALL"
    ath_price: float | None = None
    stress_price: float | None = None
    balance: float | None = None
    contract_size: float = 100.0
    current_loss: float | None = None
    risk_limit: float | None = None
    remaining_risk: float | None = None
    positions_count: int = 0
    positions: list[RiskPositionExposureRead] = field(default_factory=list)
    updated_at: datetime | None = None
    valid: bool = False
    dirty: bool = True
    message: str | None = None

    def to_read(self) -> RiskSnapshotRead:
        return RiskSnapshotRead(
            symbol=self.symbol,
            mode=self.mode,
            source=self.source,
            ath_price=self.ath_price,
            stress_price=self.stress_price,
            balance=self.balance,
            contract_size=self.contract_size,
            current_loss=self.current_loss,
            risk_limit=self.risk_limit,
            remaining_risk=self.remaining_risk,
            positions_count=self.positions_count,
            positions=self.positions,
            updated_at=self.updated_at,
            valid=self.valid,
            dirty=self.dirty,
            message=self.message,
        )


_SNAPSHOTS: dict[str, RiskSnapshot] = {}


def clear_risk_snapshot_cache() -> None:
    _SNAPSHOTS.clear()


class RiskSnapshotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_snapshot(self, symbol: str, *, source: str = "ALL", recompute_if_missing: bool = True) -> RiskSnapshot:
        normalized_symbol = symbol.upper()
        normalized_source = _normalize_source(source)
        cached = _SNAPSHOTS.get(_cache_key(normalized_symbol, normalized_source))
        if cached is not None:
            if cached.dirty and recompute_if_missing:
                return self.recompute(normalized_symbol, source=normalized_source)
            return cached
        if not recompute_if_missing:
            return _empty_snapshot(normalized_symbol, "Sin snapshot de riesgo")
        return self.recompute(normalized_symbol, source=normalized_source)

    def recompute(self, symbol: str, *, source: str = "ALL") -> RiskSnapshot:
        started = perf_counter()
        normalized_symbol = symbol.upper()
        normalized_source = _normalize_source(source)
        mapping = get_symbol_by_internal(self.db, normalized_symbol)
        contract_size = float(mapping.contract_size) if mapping is not None and mapping.contract_size and mapping.contract_size > 0 else 100.0
        account = mt5_status_store.get().account
        balance = float(account.balance) if account is not None and account.balance is not None else None
        ath_price = get_or_update_symbol_ath(self.db, normalized_symbol)
        stress_price = ath_price * 0.70 if ath_price is not None and ath_price > 0 else None
        positions = self._open_positions(normalized_symbol, normalized_source)

        position_exposures: list[RiskPositionExposureRead] = []
        current_loss = 0.0
        if stress_price is not None:
            for position in positions:
                loss = candidate_loss(
                    side=position.side,
                    volume=float(position.volume),
                    price=float(position.open_price),
                    stress_price=stress_price,
                    contract_size=contract_size,
                )
                current_loss += loss
                position_exposures.append(
                    RiskPositionExposureRead(
                        position_id=position.id,
                        internal_symbol=position.internal_symbol,
                        side=position.side,
                        volume=float(position.volume),
                        open_price=float(position.open_price),
                        loss_at_stress=round(loss, 2),
                    )
                )

        risk_limit = balance * ATH_RISK_LIMIT_RATIO if balance is not None and balance > 0 else None
        rounded_loss = round(current_loss, 2) if stress_price is not None else None
        remaining_risk = round(max(0.0, risk_limit - (rounded_loss or 0.0)), 2) if risk_limit is not None and rounded_loss is not None else None
        valid = ath_price is not None and stress_price is not None and balance is not None and balance > 0
        message = None
        if ath_price is None:
            message = "Falta ATH"
        elif balance is None or balance <= 0:
            message = "Falta balance MT5"

        snapshot = RiskSnapshot(
            symbol=normalized_symbol,
            source=normalized_source,
            ath_price=ath_price,
            stress_price=stress_price,
            balance=balance,
            contract_size=contract_size,
            current_loss=rounded_loss,
            risk_limit=round(risk_limit, 2) if risk_limit is not None else None,
            remaining_risk=remaining_risk,
            positions_count=len(positions),
            positions=position_exposures,
            updated_at=datetime.now(UTC),
            valid=valid,
            dirty=False,
            message=message,
        )
        _SNAPSHOTS[_cache_key(normalized_symbol, normalized_source)] = snapshot
        logger.info(
            "risk_snapshot_updated symbol=%s source=%s ath=%s stress_price=%s balance=%s current_loss=%s remaining_risk=%s ms=%.2f",
            normalized_symbol,
            normalized_source,
            ath_price,
            stress_price,
            balance,
            rounded_loss,
            remaining_risk,
            (perf_counter() - started) * 1000,
        )
        return snapshot

    def mark_dirty(self, symbol: str | None = None) -> None:
        if symbol is None:
            for snapshot in _SNAPSHOTS.values():
                snapshot.dirty = True
            return
        normalized_symbol = symbol.upper()
        touched = False
        for key, cached in _SNAPSHOTS.items():
            if not key.startswith(f"{normalized_symbol}:"):
                continue
            cached.dirty = True
            cached.message = "Riesgo pendiente de actualizar"
            touched = True
        if not touched:
            _SNAPSHOTS[_cache_key(normalized_symbol, "ALL")] = _empty_snapshot(normalized_symbol, "Riesgo pendiente de calcular")

    def preview_candidate(self, symbol: str, *, side: str, volume: float, price: float | None, source: str = "ALL") -> RiskCandidatePreviewRead:
        snapshot = self.get_snapshot(symbol, source=source)
        loss = None
        projected_loss = None
        projected_balance = None
        projected_balance_pct = None
        breaches_limit = False
        if snapshot.valid and snapshot.stress_price is not None and snapshot.current_loss is not None and price is not None and price > 0:
            loss = round(
                candidate_loss(
                    side=side,
                    volume=volume,
                    price=price,
                    stress_price=snapshot.stress_price,
                    contract_size=snapshot.contract_size,
                ),
                2,
            )
            projected_loss = round(snapshot.current_loss + loss, 2)
            if snapshot.balance is not None and snapshot.balance > 0:
                projected_balance = round(snapshot.balance - projected_loss, 2)
                projected_balance_pct = round((projected_loss / snapshot.balance) * 100, 2)
            breaches_limit = snapshot.risk_limit is not None and projected_loss > snapshot.risk_limit
        return RiskCandidatePreviewRead(
            snapshot=snapshot.to_read(),
            side=side.upper(),
            volume=volume,
            price=price,
            candidate_loss=loss,
            projected_loss=projected_loss,
            projected_balance=projected_balance,
            projected_balance_pct=projected_balance_pct,
            breaches_limit=breaches_limit,
            accepted_required=True,
        )

    def _open_positions(self, symbol: str, source: str) -> list[Position]:
        stmt = select(Position).where(
            Position.internal_symbol == symbol,
            Position.status == "OPEN",
        )
        if source in {"STRATEGY", "BOT"}:
            stmt = (
                stmt.join(Order, Position.order_id == Order.id)
                .where(Order.source == "STRATEGY", Order.strategy_key == "torum_v1")
            )
        return [position for position in self.db.scalars(stmt) if _is_risk_open_position(position)]


def candidate_loss(*, side: str, volume: float, price: float, stress_price: float, contract_size: float) -> float:
    if volume <= 0 or price <= 0 or stress_price <= 0 or contract_size <= 0:
        return 0.0
    if side.upper() == "BUY":
        return max(0.0, price - stress_price) * volume * contract_size
    return max(0.0, stress_price - price) * volume * contract_size


def _is_risk_open_position(position: Position) -> bool:
    if position.status != "OPEN":
        return False
    if position.closed_at is not None or position.close_price is not None:
        return False
    if position.mode != "PAPER" and position.mt5_position_ticket is None:
        return False
    return True


def _empty_snapshot(symbol: str, message: str) -> RiskSnapshot:
    return RiskSnapshot(
        symbol=symbol.upper(),
        updated_at=None,
        valid=False,
        dirty=True,
        message=message,
    )


def _cache_key(symbol: str, source: str) -> str:
    return f"{symbol.upper()}:{_normalize_source(source)}"


def _normalize_source(source: str) -> str:
    normalized = (source or "ALL").upper()
    if normalized == "BOT":
        return "STRATEGY"
    return normalized if normalized in {"ALL", "STRATEGY"} else "ALL"

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from time import perf_counter
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.mt5.client import MT5BridgeClient, MT5BridgeClientError
from app.mt5.status_store import mt5_status_store
from app.orders.models import Order
from app.positions.models import Position
from app.risk.models import RiskSnapshotRecord
from app.risk.schemas import RiskCandidatePreviewRead, RiskPositionExposureRead, RiskSnapshotRead
from app.strategies.ath import ATH_RISK_LIMIT_RATIO, get_or_update_symbol_ath
from app.symbols.service import get_symbol_by_internal
from app.trade_jobs.service import enqueue_trade_job

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskSnapshot:
    symbol: str
    mode: str = "ALL"
    source: str = "ALL"
    account_login: int | None = None
    account_server: str | None = None
    account_currency: str | None = None
    profit_currency: str | None = None
    conversion_rate: float = 1.0
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
            account_login=self.account_login,
            account_server=self.account_server,
            account_currency=self.account_currency,
            profit_currency=self.profit_currency,
            conversion_rate=self.conversion_rate,
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
_CACHE_LOCK = RLock()


def clear_risk_snapshot_cache() -> None:
    with _CACHE_LOCK:
        _SNAPSHOTS.clear()


class RiskSnapshotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_snapshot(
        self,
        symbol: str,
        *,
        source: str = "ALL",
        recompute_if_missing: bool = True,
    ) -> RiskSnapshot:
        normalized_symbol = symbol.upper()
        normalized_source = _normalize_source(source)
        account_login, account_server, _currency = _current_account_identity()
        key = _cache_key(account_login, account_server, normalized_symbol, normalized_source)
        with _CACHE_LOCK:
            cached = _SNAPSHOTS.get(key)
        if cached is not None:
            if cached.dirty:
                self._ensure_recompute_job(normalized_symbol, normalized_source, account_login, account_server)
                if cached.valid:
                    return cached
            else:
                return cached

        persisted = self._load_persisted(account_login, account_server, normalized_symbol, normalized_source)
        if persisted is not None:
            snapshot = _snapshot_from_payload(persisted.payload_json)
            snapshot.dirty = bool(persisted.dirty)
            if snapshot.dirty:
                snapshot.message = snapshot.message or "Riesgo pendiente de actualizar"
                self._ensure_recompute_job(normalized_symbol, normalized_source, account_login, account_server)
            with _CACHE_LOCK:
                _SNAPSHOTS[key] = snapshot
            if snapshot.valid or not recompute_if_missing:
                return snapshot

        if not recompute_if_missing:
            return _empty_snapshot(
                normalized_symbol,
                "Sin snapshot de riesgo",
                source=normalized_source,
                account_login=account_login,
                account_server=account_server,
            )
        return self.recompute(normalized_symbol, source=normalized_source)

    def recompute(self, symbol: str, *, source: str = "ALL") -> RiskSnapshot:
        started = perf_counter()
        normalized_symbol = symbol.upper()
        normalized_source = _normalize_source(source)
        mapping = get_symbol_by_internal(self.db, normalized_symbol)
        raw_contract_size = (
            float(mapping.contract_size)
            if mapping is not None and mapping.contract_size and mapping.contract_size > 0
            else 100.0
        )
        configured_conversion_rate = (
            float(mapping.risk_conversion_rate)
            if mapping is not None and mapping.risk_conversion_rate and mapping.risk_conversion_rate > 0
            else 1.0
        )
        conversion_rate = configured_conversion_rate
        effective_contract_size = raw_contract_size * conversion_rate
        account = mt5_status_store.get().account
        account_login = account.login if account is not None else None
        account_server = account.server if account is not None else None
        account_currency = getattr(account, "currency", None) if account is not None else None
        balance = float(account.balance) if account is not None and account.balance is not None else None
        profit_currency = mapping.profit_currency if mapping is not None else None
        ath_price = get_or_update_symbol_ath(self.db, normalized_symbol)
        stress_price = ath_price * 0.70 if ath_price is not None and ath_price > 0 else None
        calibrated = self._calibrate_contract_size_with_mt5(
            broker_symbol=mapping.broker_symbol if mapping is not None else normalized_symbol,
            reference_price=ath_price,
            stress_price=stress_price,
            raw_contract_size=raw_contract_size,
        )
        if calibrated is not None:
            effective_contract_size = calibrated
            conversion_rate = calibrated / raw_contract_size if raw_contract_size > 0 else 1.0
        positions = self._open_positions(
            normalized_symbol,
            normalized_source,
            account_login=account_login,
            account_server=account_server,
        )

        position_exposures: list[RiskPositionExposureRead] = []
        current_loss = 0.0
        if stress_price is not None:
            for position in positions:
                loss = candidate_loss(
                    side=position.side,
                    volume=float(position.volume),
                    price=float(position.open_price),
                    stress_price=stress_price,
                    contract_size=effective_contract_size,
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
        remaining_risk = (
            round(max(0.0, risk_limit - (rounded_loss or 0.0)), 2)
            if risk_limit is not None and rounded_loss is not None
            else None
        )
        valid = ath_price is not None and stress_price is not None and balance is not None and balance > 0
        message = None
        if ath_price is None:
            message = "Falta ATH"
        elif balance is None or balance <= 0:
            message = "Falta balance MT5"
        elif (
            account_currency
            and profit_currency
            and account_currency.upper() != profit_currency.upper()
            and calibrated is None
            and abs(configured_conversion_rate - 1.0) < 1e-12
        ):
            message = (
                f"Conversión {profit_currency}->{account_currency} no calibrada por MT5; "
                "se usa risk_conversion_rate=1.0"
            )

        snapshot = RiskSnapshot(
            symbol=normalized_symbol,
            source=normalized_source,
            account_login=account_login,
            account_server=account_server,
            account_currency=account_currency,
            profit_currency=profit_currency,
            conversion_rate=conversion_rate,
            ath_price=ath_price,
            stress_price=stress_price,
            balance=balance,
            contract_size=effective_contract_size,
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
        key = _cache_key(account_login, account_server, normalized_symbol, normalized_source)
        with _CACHE_LOCK:
            _SNAPSHOTS[key] = snapshot
        self._persist_snapshot(snapshot)
        logger.info(
            "risk_snapshot_updated account=%s server=%s symbol=%s source=%s ath=%s stress_price=%s "
            "balance=%s current_loss=%s remaining_risk=%s conversion_rate=%s ms=%.2f",
            account_login,
            account_server,
            normalized_symbol,
            normalized_source,
            ath_price,
            stress_price,
            balance,
            rounded_loss,
            remaining_risk,
            conversion_rate,
            (perf_counter() - started) * 1000,
        )
        return snapshot

    def mark_dirty(self, symbol: str | None = None) -> None:
        account_login, account_server, _currency = _current_account_identity()
        symbols = [symbol.upper()] if symbol else self._known_symbols(account_login, account_server)
        if not symbols:
            symbols = ["XAUUSD", "XAUEUR"]
        for normalized_symbol in symbols:
            for normalized_source in ("ALL", "STRATEGY"):
                key = _cache_key(account_login, account_server, normalized_symbol, normalized_source)
                with _CACHE_LOCK:
                    cached = _SNAPSHOTS.get(key)
                    if cached is not None:
                        cached.dirty = True
                        cached.message = "Riesgo pendiente de actualizar"
                record = self._load_persisted(account_login, account_server, normalized_symbol, normalized_source)
                if record is not None:
                    record.dirty = True
                self._ensure_recompute_job(
                    normalized_symbol,
                    normalized_source,
                    account_login,
                    account_server,
                )

    def preview_candidate(
        self,
        symbol: str,
        *,
        side: str,
        volume: float,
        price: float | None,
        source: str = "ALL",
    ) -> RiskCandidatePreviewRead:
        snapshot = self.get_snapshot(symbol, source=source)
        loss = None
        projected_loss = None
        projected_balance = None
        projected_balance_pct = None
        breaches_limit = False
        if (
            snapshot.valid
            and snapshot.stress_price is not None
            and snapshot.current_loss is not None
            and price is not None
            and price > 0
        ):
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

    def _calibrate_contract_size_with_mt5(
        self,
        *,
        broker_symbol: str,
        reference_price: float | None,
        stress_price: float | None,
        raw_contract_size: float,
    ) -> float | None:
        settings = get_settings()
        if not settings.risk_use_mt5_profit_calibration:
            return None
        if reference_price is None or stress_price is None or reference_price <= stress_price or raw_contract_size <= 0:
            return None
        try:
            response = MT5BridgeClient(timeout=settings.risk_mt5_calibration_timeout_seconds).calculate_profit(
                {
                    "broker_symbol": broker_symbol,
                    "side": "BUY",
                    "volume": 1.0,
                    "price_open": reference_price,
                    "price_close": stress_price,
                }
            )
        except MT5BridgeClientError as exc:
            logger.warning("risk_mt5_calibration_unavailable symbol=%s error=%s", broker_symbol, exc)
            return None
        profit = response.get("profit") if response.get("ok") else None
        try:
            loss = abs(float(profit))
        except (TypeError, ValueError):
            return None
        price_distance = abs(reference_price - stress_price)
        if loss <= 0 or price_distance <= 0:
            return None
        calibrated = loss / price_distance
        if calibrated <= 0:
            return None
        logger.info(
            "risk_mt5_calibrated symbol=%s raw_contract_size=%s effective_contract_size=%s",
            broker_symbol,
            raw_contract_size,
            calibrated,
        )
        return calibrated

    def _open_positions(
        self,
        symbol: str,
        source: str,
        *,
        account_login: int | None,
        account_server: str | None,
    ) -> list[Position]:
        stmt = select(Position).where(
            Position.internal_symbol == symbol,
            Position.status == "OPEN",
        )
        if account_login is not None:
            stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
        if account_server:
            stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))
        if source in {"STRATEGY", "BOT"}:
            stmt = stmt.join(Order, Position.order_id == Order.id).where(
                Order.source == "STRATEGY",
                Order.strategy_key == "torum_v1",
            )
        return [position for position in self.db.scalars(stmt) if _is_risk_open_position(position)]

    def _load_persisted(
        self,
        account_login: int | None,
        account_server: str | None,
        symbol: str,
        source: str,
    ) -> RiskSnapshotRecord | None:
        return self.db.scalar(
            select(RiskSnapshotRecord)
            .where(
                RiskSnapshotRecord.account_login == _db_login(account_login),
                RiskSnapshotRecord.account_server == _db_server(account_server),
                RiskSnapshotRecord.symbol == symbol,
                RiskSnapshotRecord.source == source,
            )
            .limit(1)
        )

    def _persist_snapshot(self, snapshot: RiskSnapshot) -> None:
        record = self._load_persisted(
            snapshot.account_login,
            snapshot.account_server,
            snapshot.symbol,
            snapshot.source,
        )
        payload = snapshot.to_read().model_dump(mode="json")
        if record is None:
            record = RiskSnapshotRecord(
                account_login=_db_login(snapshot.account_login),
                account_server=_db_server(snapshot.account_server),
                symbol=snapshot.symbol,
                source=snapshot.source,
                payload_json=payload,
                valid=snapshot.valid,
                dirty=False,
            )
            self.db.add(record)
        else:
            record.payload_json = payload
            record.valid = snapshot.valid
            record.dirty = False

    def _ensure_recompute_job(
        self,
        symbol: str,
        source: str,
        account_login: int | None,
        account_server: str | None,
    ) -> None:
        key = f"risk:{_db_login(account_login)}:{_db_server(account_server)}:{symbol}:{source}"
        enqueue_trade_job(
            self.db,
            job_type="RECOMPUTE_RISK",
            idempotency_key=key,
            payload={"symbol": symbol, "source": source},
            reactivate_completed=True,
        )

    def _known_symbols(self, account_login: int | None, account_server: str | None) -> list[str]:
        records = self.db.scalars(
            select(RiskSnapshotRecord.symbol).where(
                RiskSnapshotRecord.account_login == _db_login(account_login),
                RiskSnapshotRecord.account_server == _db_server(account_server),
            )
        )
        return sorted(set(records))


def candidate_loss(
    *,
    side: str,
    volume: float,
    price: float,
    stress_price: float,
    contract_size: float,
) -> float:
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


def _empty_snapshot(
    symbol: str,
    message: str,
    *,
    source: str = "ALL",
    account_login: int | None = None,
    account_server: str | None = None,
) -> RiskSnapshot:
    return RiskSnapshot(
        symbol=symbol.upper(),
        source=_normalize_source(source),
        account_login=account_login,
        account_server=account_server,
        updated_at=None,
        valid=False,
        dirty=True,
        message=message,
    )


def _current_account_identity() -> tuple[int | None, str | None, str | None]:
    account = mt5_status_store.get().account
    if account is None:
        return None, None, None
    return account.login, account.server, getattr(account, "currency", None)


def _cache_key(account_login: int | None, account_server: str | None, symbol: str, source: str) -> str:
    return f"{_db_login(account_login)}:{_db_server(account_server)}:{symbol.upper()}:{_normalize_source(source)}"


def _db_login(value: int | None) -> int:
    return int(value or 0)


def _db_server(value: str | None) -> str:
    return str(value or "")


def _normalize_source(source: str) -> str:
    normalized = (source or "ALL").upper()
    if normalized == "BOT":
        return "STRATEGY"
    return normalized if normalized in {"ALL", "STRATEGY"} else "ALL"


def _snapshot_from_payload(payload: dict[str, Any]) -> RiskSnapshot:
    read = RiskSnapshotRead.model_validate(payload)
    return RiskSnapshot(
        symbol=read.symbol,
        mode=read.mode,
        source=read.source,
        account_login=read.account_login,
        account_server=read.account_server,
        account_currency=read.account_currency,
        profit_currency=read.profit_currency,
        conversion_rate=read.conversion_rate,
        ath_price=read.ath_price,
        stress_price=read.stress_price,
        balance=read.balance,
        contract_size=read.contract_size,
        current_loss=read.current_loss,
        risk_limit=read.risk_limit,
        remaining_risk=read.remaining_risk,
        positions_count=read.positions_count,
        positions=read.positions,
        updated_at=read.updated_at,
        valid=read.valid,
        dirty=read.dirty,
        message=read.message,
    )

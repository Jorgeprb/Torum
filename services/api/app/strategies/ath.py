from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.orders.models import Order
from app.positions.models import Position
from app.strategies.ath_models import SymbolAthLevel
from app.strategies.models import StrategySignal
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.lot_sizing import calculate_lot_size

ATH_SYMBOLS = {"XAUUSD", "XAUEUR"}
ATH_RISK_LIMIT_RATIO = 0.50
ATH_ADVERSE_MOVE_RATIO = 0.30
ATH_AUTO_SOURCE = "candles"
ATH_MANUAL_SOURCE = "manual"
TORUM_V1_PENDING_ORDER_STATUSES = ("CREATED", "VALIDATING", "SENT")
TORUM_V1_RESERVED_SIGNAL_STATUSES = ("RISK_APPROVED", "SENT_TO_ORDER_MANAGER")


@dataclass(frozen=True, slots=True)
class AthRiskZone:
    key: str
    label: str
    price_min: float | None
    price_max: float
    color: str
    max_lot_equivalents: int


@dataclass(frozen=True, slots=True)
class BotExposurePlan:
    allowed: bool
    multiplier: int
    volume: float
    reason: str
    ath_price: float | None
    ath_zone: str | None
    max_lot_equivalents: int
    open_lot_equivalents: float
    potential_loss: float | None
    projected_balance: float | None


@dataclass(frozen=True, slots=True)
class RiskPreview:
    balance: float | None
    potential_loss: float | None
    projected_balance: float | None
    breaches_bot_limit: bool
    positions_count: int


def get_or_update_symbol_ath(db: Session, symbol: str) -> float | None:
    normalized_symbol = symbol.upper()
    if normalized_symbol not in ATH_SYMBOLS:
        return None

    highest = db.scalar(select(func.max(Candle.high)).where(Candle.internal_symbol == normalized_symbol))
    existing = db.get(SymbolAthLevel, normalized_symbol)

    if existing is not None and existing.source == ATH_MANUAL_SOURCE:
        return existing.ath_price

    if highest is None:
        return existing.ath_price if existing is not None else None

    highest_float = float(highest)
    if existing is None:
        existing = SymbolAthLevel(internal_symbol=normalized_symbol, ath_price=highest_float, source=ATH_AUTO_SOURCE, calculated_at=datetime.now(UTC))
        db.add(existing)
        db.commit()
        return highest_float

    if highest_float > existing.ath_price:
        existing.ath_price = highest_float
        existing.source = ATH_AUTO_SOURCE
        existing.calculated_at = datetime.now(UTC)
        db.commit()

    return max(highest_float, existing.ath_price)


def list_symbol_ath_levels(db: Session) -> list[SymbolAthLevel | None]:
    levels: list[SymbolAthLevel | None] = []
    for symbol in sorted(ATH_SYMBOLS):
        get_or_update_symbol_ath(db, symbol)
        levels.append(db.get(SymbolAthLevel, symbol))
    return levels


def set_symbol_ath_level(db: Session, symbol: str, mode: str, ath_price: float | None = None) -> SymbolAthLevel:
    normalized_symbol = symbol.upper()
    if normalized_symbol not in ATH_SYMBOLS:
        raise ValueError("unsupported_symbol")

    now = datetime.now(UTC)
    existing = db.get(SymbolAthLevel, normalized_symbol)
    if mode == "manual":
        if ath_price is None or ath_price <= 0:
            raise ValueError("manual_ath_required")
        if existing is None:
            existing = SymbolAthLevel(
                internal_symbol=normalized_symbol,
                ath_price=float(ath_price),
                source=ATH_MANUAL_SOURCE,
                calculated_at=now,
            )
            db.add(existing)
        else:
            existing.ath_price = float(ath_price)
            existing.source = ATH_MANUAL_SOURCE
            existing.calculated_at = now
        db.commit()
        db.refresh(existing)
        return existing

    if mode != "auto":
        raise ValueError("invalid_mode")

    highest = db.scalar(select(func.max(Candle.high)).where(Candle.internal_symbol == normalized_symbol))
    if highest is None:
        raise ValueError("missing_auto_ath")

    if existing is None:
        existing = SymbolAthLevel(
            internal_symbol=normalized_symbol,
            ath_price=float(highest),
            source=ATH_AUTO_SOURCE,
            calculated_at=now,
        )
        db.add(existing)
    else:
        existing.ath_price = float(highest)
        existing.source = ATH_AUTO_SOURCE
        existing.calculated_at = now
    db.commit()
    db.refresh(existing)
    return existing


def ath_price_zones(db: Session, symbol: str) -> list[dict[str, object]]:
    ath = get_or_update_symbol_ath(db, symbol)
    if ath is None or ath <= 0:
        return []

    return [
        _zone_payload(zone, ath)
        for zone in _zones_for_ath(ath)
    ]


def ath_zone_for_price(ath_price: float | None, price: float | None) -> AthRiskZone | None:
    if ath_price is None or ath_price <= 0 or price is None or price <= 0:
        return None

    zones = _zones_for_ath(ath_price)
    for zone in zones:
        lower_ok = zone.price_min is None or price >= zone.price_min
        if lower_ok and price <= zone.price_max:
            return zone

    if price < ath_price * 0.70:
        return AthRiskZone("deep_green", "VERDE -30%+", None, ath_price * 0.70, "#32d074", 3)

    return zones[0]


def ath_zone_for_price_config(
    ath_price: float | None,
    price: float | None,
    params: dict[str, object] | None = None,
) -> AthRiskZone | None:
    if not params:
        return ath_zone_for_price(ath_price, price)
    if ath_price is None or ath_price <= 0 or price is None or price <= 0:
        return None
    red = _float_or_none(params.get("ath_red_limit_pct")) or 2.5
    orange = _float_or_none(params.get("ath_orange_limit_pct")) or 9.0
    yellow = _float_or_none(params.get("ath_yellow_limit_pct")) or 15.0
    green = _float_or_none(params.get("ath_green_limit_pct")) or 30.0
    drop_pct = max(0.0, (ath_price - price) / ath_price * 100.0)
    if drop_pct <= red:
        return AthRiskZone("red", "ROJA", ath_price * (1 - red / 100), ath_price, "#ef4444", 0)
    if drop_pct <= orange:
        return AthRiskZone("orange", "NARANJA", ath_price * (1 - orange / 100), ath_price * (1 - red / 100), "#f59e0b", 1)
    if drop_pct <= yellow:
        return AthRiskZone("yellow", "AMARILLA", ath_price * (1 - yellow / 100), ath_price * (1 - orange / 100), "#eab308", 2)
    if drop_pct <= green:
        return AthRiskZone("green", "VERDE", ath_price * (1 - green / 100), ath_price * (1 - yellow / 100), "#32d074", 3)
    return AthRiskZone("deep_green", f"VERDE -{green:.0f}%+", None, ath_price * (1 - green / 100), "#32d074", 3)


def bot_open_positions(db: Session, symbol: str, user_id: int | None = None) -> list[Position]:
    stmt = (
        select(Position)
        .join(Order, Position.order_id == Order.id)
        .where(
            Position.internal_symbol == symbol.upper(),
            Position.status == "OPEN",
            Order.source == "STRATEGY",
            Order.strategy_key == "torum_v1",
        )
    )
    if user_id is not None:
        stmt = stmt.where(Position.user_id == user_id)
    return [position for position in db.scalars(stmt) if _is_live_bot_position(position)]


def _is_live_bot_position(position: Position) -> bool:
    if position.status != "OPEN":
        return False
    if position.closed_at is not None or position.close_price is not None:
        return False
    if position.mode != "PAPER" and position.mt5_position_ticket is None:
        return False
    return True


def open_lot_equivalents(positions: Iterable[Position], base_lot: float) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    return sum(max(0.0, float(position.volume)) / safe_base for position in positions)


def bot_pending_lot_equivalents(db: Session, symbol: str, user_id: int | None, base_lot: float, exclude_order_id: int | None = None) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    stmt = select(Order).where(
        Order.internal_symbol == symbol.upper(),
        Order.source == "STRATEGY",
        Order.strategy_key == "torum_v1",
        Order.status.in_(TORUM_V1_PENDING_ORDER_STATUSES),
    )
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    if exclude_order_id is not None:
        stmt = stmt.where(Order.id != exclude_order_id)
    return sum(max(0.0, float(order.volume)) / safe_base for order in db.scalars(stmt))


def bot_reserved_signal_lot_equivalents(db: Session, symbol: str, user_id: int | None, base_lot: float, exclude_signal_id: int | None = None) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    stmt = select(StrategySignal).where(
        StrategySignal.strategy_key == "torum_v1",
        StrategySignal.internal_symbol == symbol.upper(),
        StrategySignal.signal_type == "ENTRY",
        StrategySignal.side == "BUY",
        StrategySignal.status.in_(TORUM_V1_RESERVED_SIGNAL_STATUSES),
    )
    if user_id is not None:
        stmt = stmt.where(StrategySignal.user_id == user_id)
    if exclude_signal_id is not None:
        stmt = stmt.where(StrategySignal.id != exclude_signal_id)

    total = 0.0
    for signal in db.scalars(stmt):
        metadata = signal.metadata_json or {}
        volume = _float_or_none(metadata.get("accepted_volume")) or _float_or_none(signal.suggested_volume)
        if volume is not None:
            total += max(0.0, volume) / safe_base
            continue
        multiplier = _float_or_none(metadata.get("accepted_multiplier")) or _float_or_none(metadata.get("desired_multiplier")) or 1.0
        total += max(0.0, multiplier)
    return total


def bot_reserved_potential_loss(
    db: Session,
    symbol: str,
    user_id: int | None,
    *,
    stress_price: float,
    contract_size: float,
    fallback_price: float | None,
    exclude_order_id: int | None = None,
    exclude_signal_id: int | None = None,
) -> float:
    from app.risk.snapshot import candidate_loss

    total = 0.0
    order_stmt = select(Order).where(
        Order.internal_symbol == symbol.upper(),
        Order.source == "STRATEGY",
        Order.strategy_key == "torum_v1",
        Order.status.in_(TORUM_V1_PENDING_ORDER_STATUSES),
    )
    if user_id is not None:
        order_stmt = order_stmt.where(Order.user_id == user_id)
    if exclude_order_id is not None:
        order_stmt = order_stmt.where(Order.id != exclude_order_id)
    for order in db.scalars(order_stmt):
        price = order.executed_price or order.requested_price or fallback_price
        if price is None:
            continue
        total += candidate_loss(
            side=order.side,
            volume=float(order.volume),
            price=float(price),
            stress_price=stress_price,
            contract_size=contract_size,
        )

    signal_stmt = select(StrategySignal).where(
        StrategySignal.strategy_key == "torum_v1",
        StrategySignal.internal_symbol == symbol.upper(),
        StrategySignal.signal_type == "ENTRY",
        StrategySignal.side == "BUY",
        StrategySignal.status.in_(TORUM_V1_RESERVED_SIGNAL_STATUSES),
    )
    if user_id is not None:
        signal_stmt = signal_stmt.where(StrategySignal.user_id == user_id)
    if exclude_signal_id is not None:
        signal_stmt = signal_stmt.where(StrategySignal.id != exclude_signal_id)
    for signal in db.scalars(signal_stmt):
        metadata = signal.metadata_json or {}
        volume = _float_or_none(metadata.get("accepted_volume")) or _float_or_none(signal.suggested_volume)
        price = fallback_price or _float_or_none(metadata.get("current_price"))
        if volume is None or price is None:
            continue
        total += candidate_loss(
            side=signal.side,
            volume=volume,
            price=price,
            stress_price=stress_price,
            contract_size=contract_size,
        )
    return round(total, 2)


def plan_torum_v1_bot_exposure(
    db: Session,
    *,
    symbol: str,
    user_id: int | None,
    desired_multiplier: int,
    current_price: float | None,
    balance: float | None,
    trading_settings: object,
    symbol_mapping: SymbolMapping | None,
    strategy_params: dict[str, object] | None = None,
    exclude_order_id: int | None = None,
    exclude_signal_id: int | None = None,
) -> BotExposurePlan:
    normalized_symbol = symbol.upper()
    base_lot = _base_lot(balance, trading_settings)
    ath = get_or_update_symbol_ath(db, normalized_symbol)
    zone = ath_zone_for_price_config(ath, current_price, strategy_params)
    configured_max_equivalents = int(_float_or_none((strategy_params or {}).get("max_equivalent_positions")) or 3)
    max_equivalents = min(zone.max_lot_equivalents if zone is not None else 1, configured_max_equivalents)
    if zone is not None and zone.max_lot_equivalents <= 0:
        return _blocked("ath_red_zone", ath, zone, max_equivalents, 0.0)

    open_positions = bot_open_positions(db, normalized_symbol, user_id)
    open_equiv = open_lot_equivalents(open_positions, base_lot)
    pending_equiv = bot_pending_lot_equivalents(db, normalized_symbol, user_id, base_lot, exclude_order_id=exclude_order_id)
    reserved_equiv = bot_reserved_signal_lot_equivalents(db, normalized_symbol, user_id, base_lot, exclude_signal_id=exclude_signal_id)
    used_equiv = open_equiv + pending_equiv + reserved_equiv
    max_multiplier = min(max(1, int(desired_multiplier)), configured_max_equivalents)
    allow_degrade = bool((strategy_params or {}).get("support_degrade_enabled", True))

    if balance is None or balance <= 0:
        return _blocked("missing_account_balance", ath, zone, max_equivalents, open_equiv)
    if current_price is None or current_price <= 0:
        return _blocked("missing_current_price", ath, zone, max_equivalents, open_equiv)

    from app.risk.snapshot import RiskSnapshotService, candidate_loss

    snapshot = RiskSnapshotService(db).get_snapshot(normalized_symbol, source="STRATEGY")
    if snapshot.dirty or not snapshot.valid:
        snapshot = RiskSnapshotService(db).recompute(normalized_symbol, source="STRATEGY")
    if not snapshot.valid or snapshot.stress_price is None:
        return _blocked("missing_risk_snapshot", ath, zone, max_equivalents, used_equiv)
    stress_drop_pct = _float_or_none((strategy_params or {}).get("risk_stress_drop_from_ath_pct")) or (ATH_ADVERSE_MOVE_RATIO * 100.0)
    stress_price = ath * (1.0 - stress_drop_pct / 100.0) if ath is not None else snapshot.stress_price
    risk_limit_pct = _float_or_none((strategy_params or {}).get("risk_max_balance_pct")) or (ATH_RISK_LIMIT_RATIO * 100.0)
    risk_limit = balance * risk_limit_pct / 100.0
    from app.risk.snapshot import candidate_loss
    current_loss = round(
        sum(
            candidate_loss(
                side=item.side,
                volume=float(item.volume),
                price=float(item.open_price),
                stress_price=stress_price,
                contract_size=snapshot.contract_size,
            )
            for item in snapshot.positions
        ),
        2,
    )
    reserved_loss = bot_reserved_potential_loss(
        db,
        normalized_symbol,
        user_id,
        stress_price=stress_price,
        contract_size=snapshot.contract_size,
        fallback_price=current_price,
        exclude_order_id=exclude_order_id,
        exclude_signal_id=exclude_signal_id,
    )
    current_loss = round(current_loss + reserved_loss, 2)
    if not allow_degrade and used_equiv + max_multiplier > max_equivalents + 1e-9:
        return _blocked("requested_multiplier_does_not_fit", ath, zone, max_equivalents, used_equiv)

    multipliers = range(max_multiplier, 0, -1) if allow_degrade else (max_multiplier,)
    for multiplier in multipliers:
        if used_equiv + multiplier > max_equivalents + 1e-9:
            continue
        volume = round(base_lot * multiplier, 8)
        added_loss = candidate_loss(
            side="BUY",
            volume=volume,
            price=current_price,
            stress_price=stress_price,
            contract_size=snapshot.contract_size,
        )
        potential_loss = round(current_loss + added_loss, 2)
        projected_balance = balance - potential_loss
        if potential_loss <= risk_limit:
            return BotExposurePlan(
                allowed=True,
                multiplier=multiplier,
                volume=volume,
                reason="allowed",
                ath_price=ath,
                ath_zone=zone.key if zone is not None else None,
                max_lot_equivalents=max_equivalents,
                open_lot_equivalents=used_equiv,
                potential_loss=potential_loss,
                projected_balance=projected_balance,
            )

    return BotExposurePlan(
        allowed=False,
        multiplier=0,
        volume=0.0,
        reason="risk_or_ath_capacity_exceeded" if allow_degrade else "risk_limit_exceeded",
        ath_price=ath,
        ath_zone=zone.key if zone is not None else None,
        max_lot_equivalents=max_equivalents,
        open_lot_equivalents=used_equiv,
        potential_loss=None,
        projected_balance=None,
    )


def preview_manual_risk(
    db: Session,
    *,
    symbol: str,
    side: str,
    volume: float,
    price: float | None,
    balance: float | None,
    contract_size: float,
) -> RiskPreview:
    del contract_size
    from app.risk.snapshot import RiskSnapshotService, candidate_loss

    snapshot = RiskSnapshotService(db).get_snapshot(symbol)
    if snapshot.dirty or not snapshot.valid:
        snapshot = RiskSnapshotService(db).recompute(symbol)
    if (
        not snapshot.valid
        or snapshot.current_loss is None
        or snapshot.stress_price is None
        or balance is None
        or balance <= 0
        or price is None
        or price <= 0
    ):
        return RiskPreview(balance=balance, potential_loss=None, projected_balance=None, breaches_bot_limit=False, positions_count=snapshot.positions_count)
    loss = round(
        snapshot.current_loss
        + candidate_loss(
            side=side.upper(),
            volume=volume,
            price=price,
            stress_price=snapshot.stress_price,
            contract_size=snapshot.contract_size,
        ),
        2,
    )
    projected = balance - loss
    return RiskPreview(
        balance=balance,
        potential_loss=loss,
        projected_balance=projected,
        breaches_bot_limit=loss > balance * ATH_RISK_LIMIT_RATIO,
        positions_count=snapshot.positions_count + 1,
    )


def total_potential_loss_after_adverse_move(
    *,
    positions: Iterable[Position],
    new_symbol: str | None = None,
    new_side: str | None = None,
    new_volume: float | None = None,
    new_price: float | None = None,
    contract_size: float = 100.0,
    contract_sizes: dict[str, float] | None = None,
) -> float:
    total = 0.0
    for position in positions:
        position_contract_size = (contract_sizes or {}).get(position.internal_symbol.upper(), contract_size)
        total += potential_loss_after_adverse_move(
            side=position.side,
            volume=position.volume,
            entry_price=position.open_price,
            contract_size=position_contract_size,
        )
    if new_symbol and new_side and new_volume and new_price:
        total += potential_loss_after_adverse_move(
            side=new_side,
            volume=new_volume,
            entry_price=new_price,
            contract_size=contract_size,
        )
    return round(total, 2)


def potential_loss_after_adverse_move(*, side: str, volume: float, entry_price: float, contract_size: float) -> float:
    if entry_price <= 0 or volume <= 0 or contract_size <= 0:
        return 0.0
    return abs(entry_price * ATH_ADVERSE_MOVE_RATIO * volume * contract_size)


def latest_executable_price(tick: Tick | None, side: str = "BUY") -> float | None:
    if tick is None:
        return None
    if side.upper() == "BUY":
        return tick.ask or tick.last or tick.bid
    return tick.bid or tick.last or tick.ask


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _base_lot(balance: float | None, trading_settings: object) -> float:
    return calculate_lot_size(
        available_equity=balance,
        equity_per_0_01_lot=getattr(trading_settings, "equity_per_0_01_lot", 2500.0),
        minimum_lot=getattr(trading_settings, "minimum_lot", 0.01),
        multiplier=1,
        enabled=getattr(trading_settings, "lot_per_equity_enabled", True),
    ).base_lot


def _zones_for_ath(ath: float) -> list[AthRiskZone]:
    return [
        AthRiskZone("red", "ROJA", ath * 0.975, ath, "#f45d5d", 0),
        AthRiskZone("orange", "NARANJA", ath * 0.91, ath * 0.975, "#ff9f43", 1),
        AthRiskZone("yellow", "AMARILLA", ath * 0.85, ath * 0.91, "#f5d04c", 2),
        AthRiskZone("green", "VERDE", ath * 0.70, ath * 0.85, "#32d074", 3),
    ]


def _zone_payload(zone: AthRiskZone, ath: float) -> dict[str, object]:
    return {
        "key": zone.key,
        "label": zone.label,
        "ath_price": ath,
        "price_min": zone.price_min,
        "price_max": zone.price_max,
        "color": zone.color,
        "max_lot_equivalents": zone.max_lot_equivalents,
    }


def _blocked(
    reason: str,
    ath: float | None,
    zone: AthRiskZone | None,
    max_equivalents: int,
    open_equiv: float,
) -> BotExposurePlan:
    return BotExposurePlan(
        allowed=False,
        multiplier=0,
        volume=0.0,
        reason=reason,
        ath_price=ath,
        ath_zone=zone.key if zone is not None else None,
        max_lot_equivalents=max_equivalents,
        open_lot_equivalents=open_equiv,
        potential_loss=None,
        projected_balance=None,
    )

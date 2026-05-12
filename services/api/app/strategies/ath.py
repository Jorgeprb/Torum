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
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.lot_sizing import calculate_lot_size

ATH_SYMBOLS = {"XAUUSD", "XAUEUR"}
ATH_RISK_LIMIT_RATIO = 0.50
ATH_ADVERSE_MOVE_RATIO = 0.30
ATH_AUTO_SOURCE = "candles"
ATH_MANUAL_SOURCE = "manual"


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
    return list(db.scalars(stmt))


def open_lot_equivalents(positions: Iterable[Position], base_lot: float) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    return sum(max(0.0, float(position.volume)) / safe_base for position in positions)


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
) -> BotExposurePlan:
    normalized_symbol = symbol.upper()
    base_lot = _base_lot(balance, trading_settings)
    ath = get_or_update_symbol_ath(db, normalized_symbol)
    zone = ath_zone_for_price(ath, current_price)
    max_equivalents = zone.max_lot_equivalents if zone is not None else 1
    if zone is not None and zone.max_lot_equivalents <= 0:
        return _blocked("ath_red_zone", ath, zone, max_equivalents, 0.0)

    open_positions = bot_open_positions(db, normalized_symbol, user_id)
    open_equiv = open_lot_equivalents(open_positions, base_lot)
    max_multiplier = min(max(1, int(desired_multiplier)), 3)
    contract_size = float(symbol_mapping.contract_size) if symbol_mapping is not None else 100.0

    if balance is None or balance <= 0:
        return _blocked("missing_account_balance", ath, zone, max_equivalents, open_equiv)

    for multiplier in range(max_multiplier, 0, -1):
        if open_equiv + multiplier > max_equivalents + 1e-9:
            continue
        volume = round(base_lot * multiplier, 8)
        potential_loss = total_potential_loss_after_adverse_move(
            positions=open_positions,
            new_symbol=normalized_symbol,
            new_side="BUY",
            new_volume=volume,
            new_price=current_price,
            contract_size=contract_size,
        )
        projected_balance = balance - potential_loss
        if potential_loss <= balance * ATH_RISK_LIMIT_RATIO:
            return BotExposurePlan(
                allowed=True,
                multiplier=multiplier,
                volume=volume,
                reason="allowed",
                ath_price=ath,
                ath_zone=zone.key if zone is not None else None,
                max_lot_equivalents=max_equivalents,
                open_lot_equivalents=open_equiv,
                potential_loss=potential_loss,
                projected_balance=projected_balance,
            )

    return BotExposurePlan(
        allowed=False,
        multiplier=0,
        volume=0.0,
        reason="risk_or_ath_capacity_exceeded",
        ath_price=ath,
        ath_zone=zone.key if zone is not None else None,
        max_lot_equivalents=max_equivalents,
        open_lot_equivalents=open_equiv,
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
    positions = list(db.scalars(select(Position).where(Position.status == "OPEN")))
    if balance is None or balance <= 0 or price is None or price <= 0:
        return RiskPreview(balance=balance, potential_loss=None, projected_balance=None, breaches_bot_limit=False, positions_count=len(positions))

    loss = total_potential_loss_after_adverse_move(
        positions=positions,
        new_symbol=symbol.upper(),
        new_side=side.upper(),
        new_volume=volume,
        new_price=price,
        contract_size=contract_size,
    )
    projected = balance - loss
    return RiskPreview(
        balance=balance,
        potential_loss=loss,
        projected_balance=projected,
        breaches_bot_limit=loss > balance * ATH_RISK_LIMIT_RATIO,
        positions_count=len(positions) + 1,
    )


def total_potential_loss_after_adverse_move(
    *,
    positions: Iterable[Position],
    new_symbol: str | None = None,
    new_side: str | None = None,
    new_volume: float | None = None,
    new_price: float | None = None,
    contract_size: float = 100.0,
) -> float:
    total = 0.0
    for position in positions:
        total += potential_loss_after_adverse_move(
            side=position.side,
            volume=position.volume,
            entry_price=position.open_price,
            contract_size=contract_size,
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

from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import UTC, datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.core.config import get_settings
from app.orders.models import Order
from app.positions.models import Position
from app.strategies.ath_models import SymbolAthLevel
from app.strategies.models import StrategyConfig, StrategySignal
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.lot_sizing import calculate_lot_size

ATH_SYMBOLS = {"XAUUSD", "XAUEUR"}
ATH_RISK_LIMIT_RATIO = 0.50
ATH_ADVERSE_MOVE_RATIO = 0.30
ATH_AUTO_SOURCE = "candles"
ATH_MANUAL_SOURCE = "manual"
TORUM_V1_PENDING_ORDER_STATUSES = ("CREATED", "VALIDATING", "SENT", "RECONCILING")
TORUM_V1_RESERVED_SIGNAL_STATUSES = ("RISK_APPROVED", "SENT_TO_ORDER_MANAGER", "ORDER_RECONCILING")
# Reservations are only meaningful while the synchronous order pipeline is alive.
# The actual TTL is configurable and intentionally short: the normal pipeline is
# sub-second and the MT5 request timeout is measured in seconds, not minutes.
TORUM_V1_RESERVATION_TTL = timedelta(seconds=120)


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


def get_or_update_symbol_ath(db: Session, symbol: str, *, refresh: bool = False) -> float | None:
    """Return the persisted ATH without scanning the candle table on entries.

    ATH is updated incrementally during candle ingestion. A full MAX(high) scan
    is only needed for initial bootstrap or an explicit refresh from the admin UI.
    """

    normalized_symbol = symbol.upper()
    if normalized_symbol not in ATH_SYMBOLS:
        return None

    existing = db.get(SymbolAthLevel, normalized_symbol)
    if existing is not None and (existing.source == ATH_MANUAL_SOURCE or not refresh):
        return float(existing.ath_price)

    highest = db.scalar(select(func.max(Candle.high)).where(Candle.internal_symbol == normalized_symbol))
    if highest is None:
        return float(existing.ath_price) if existing is not None else None

    highest_float = float(highest)
    if existing is None:
        existing = SymbolAthLevel(
            internal_symbol=normalized_symbol,
            ath_price=highest_float,
            source=ATH_AUTO_SOURCE,
            calculated_at=datetime.now(UTC),
        )
        db.add(existing)
    elif highest_float > float(existing.ath_price) or refresh:
        existing.ath_price = max(highest_float, float(existing.ath_price))
        existing.source = ATH_AUTO_SOURCE
        existing.calculated_at = datetime.now(UTC)
    db.commit()
    return float(existing.ath_price)


def update_symbol_ath_from_candles(db: Session, candles: Iterable[Candle]) -> set[str]:
    """Incrementally persist ATH values from the candles already ingested."""

    highs: dict[str, float] = {}
    for candle in candles:
        symbol = str(candle.internal_symbol).upper()
        if symbol not in ATH_SYMBOLS:
            continue
        high = float(candle.high)
        previous = highs.get(symbol)
        if previous is None or high > previous:
            highs[symbol] = high

    changed: set[str] = set()
    now = datetime.now(UTC)
    for symbol, high in highs.items():
        existing = db.get(SymbolAthLevel, symbol)
        if existing is not None and existing.source == ATH_MANUAL_SOURCE:
            continue
        if existing is None:
            # Bootstrap from all persisted candles once. Seeding the ATH from
            # only the current tick bucket would silently understate the real
            # all-time high and could classify risk zones incorrectly.
            historical_high = db.scalar(
                select(func.max(Candle.high)).where(Candle.internal_symbol == symbol)
            )
            bootstrap_high = max(high, float(historical_high)) if historical_high is not None else high
            db.add(SymbolAthLevel(
                internal_symbol=symbol,
                ath_price=bootstrap_high,
                source=ATH_AUTO_SOURCE,
                calculated_at=now,
            ))
            changed.add(symbol)
        elif high > float(existing.ath_price):
            existing.ath_price = high
            existing.source = ATH_AUTO_SOURCE
            existing.calculated_at = now
            changed.add(symbol)
    if changed:
        db.commit()
    return changed


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


def bot_open_positions(
    db: Session,
    symbol: str,
    user_id: int | None = None,
    *,
    mode: str | None = None,
    account_login: int | None = None,
    account_server: str | None = None,
) -> list[Position]:
    """Return live Torum positions that consume equivalent-position capacity.

    Capacity is shared between automatic Torum V1 entries and manual orders
    opened from Torum.  An arbitrary MT5 position imported without a Torum
    ``Order`` row is intentionally excluded: the user asked the strategy limit
    to govern Torum's own exposure, not unrelated broker positions.
    """

    stmt = (
        select(Position)
        .join(Order, Position.order_id == Order.id)
        .where(
            Position.internal_symbol == symbol.upper(),
            Position.status == "OPEN",
            or_(
                and_(Order.source == "STRATEGY", Order.strategy_key == "torum_v1"),
                Order.source == "MANUAL",
            ),
        )
    )
    if user_id is not None:
        stmt = stmt.where(Position.user_id == user_id)
    if mode is not None:
        stmt = stmt.where(Position.mode == mode.upper())
    if account_login is not None:
        # Keep legacy/open rows whose account identity has not yet been
        # backfilled. Ignoring them could allow a second entry while a real MT5
        # position is still open.
        stmt = stmt.where(or_(Position.account_login == account_login, Position.account_login.is_(None)))
    if account_server:
        stmt = stmt.where(or_(Position.account_server == account_server, Position.account_server.is_(None)))
    return [position for position in db.scalars(stmt) if _is_live_bot_position(position)]


def _is_live_bot_position(position: Position) -> bool:
    if position.status != "OPEN":
        return False
    if position.closed_at is not None or position.close_price is not None:
        return False
    if (
        position.mode != "PAPER"
        and position.mt5_position_ticket is None
        and position.mt5_position_identifier is None
    ):
        return False
    return True


def open_lot_equivalents(positions: Iterable[Position], base_lot: float) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    return sum(max(0.0, float(position.volume)) / safe_base for position in positions)


def _reservation_cutoff() -> datetime:
    seconds = max(15, int(get_settings().torum_reservation_ttl_seconds))
    return datetime.now(UTC) - timedelta(seconds=seconds)


def _ambiguous_reservation_cutoff() -> datetime:
    # Once the request may have crossed the broker boundary, releasing the
    # reservation merely because the normal sub-second pipeline TTL elapsed can
    # create a duplicate/over-sized second order. Healthy MT5 position+deal sync
    # resolves these rows explicitly; this longer window is only a fail-safe for
    # prolonged bridge outages.
    seconds = max(300, int(get_settings().torum_ambiguous_reservation_ttl_seconds))
    return datetime.now(UTC) - timedelta(seconds=seconds)


def _active_pending_orders(
    db: Session,
    symbol: str,
    user_id: int | None,
    *,
    exclude_order_id: int | None = None,
    mode: str | None = None,
    account_login: int | None = None,
    account_server: str | None = None,
) -> list[Order]:
    stmt = select(Order).where(
        Order.internal_symbol == symbol.upper(),
        Order.source == "STRATEGY",
        Order.strategy_key == "torum_v1",
        or_(
            and_(
                Order.status.in_(("CREATED", "VALIDATING")),
                Order.created_at >= _reservation_cutoff(),
            ),
            and_(
                Order.status.in_(("SENT", "RECONCILING")),
                Order.created_at >= _ambiguous_reservation_cutoff(),
            ),
        ),
    )
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    if mode is not None:
        stmt = stmt.where(Order.mode == mode.upper())
    if account_login is not None:
        stmt = stmt.where(or_(Order.account_login == account_login, Order.account_login.is_(None)))
    if account_server:
        stmt = stmt.where(or_(Order.account_server == account_server, Order.account_server.is_(None)))
    if exclude_order_id is not None:
        stmt = stmt.where(Order.id != exclude_order_id)
    return list(db.scalars(stmt))


def _active_reserved_signals(
    db: Session,
    symbol: str,
    user_id: int | None,
    *,
    exclude_signal_id: int | None = None,
    mode: str | None = None,
) -> list[StrategySignal]:
    stmt = select(StrategySignal)
    if mode is not None:
        stmt = stmt.join(StrategyConfig, StrategySignal.strategy_config_id == StrategyConfig.id)
    stmt = stmt.where(
        StrategySignal.strategy_key == "torum_v1",
        StrategySignal.internal_symbol == symbol.upper(),
        StrategySignal.signal_type == "ENTRY",
        StrategySignal.side == "BUY",
        or_(
            and_(
                StrategySignal.status == "RISK_APPROVED",
                StrategySignal.created_at >= _reservation_cutoff(),
            ),
            and_(
                StrategySignal.status.in_(("SENT_TO_ORDER_MANAGER", "ORDER_RECONCILING")),
                StrategySignal.created_at >= _ambiguous_reservation_cutoff(),
            ),
        ),
    )
    if user_id is not None:
        stmt = stmt.where(StrategySignal.user_id == user_id)
    if mode is not None:
        stmt = stmt.where(StrategyConfig.mode == mode.upper())
    if exclude_signal_id is not None:
        stmt = stmt.where(StrategySignal.id != exclude_signal_id)
    return list(db.scalars(stmt))


def bot_pending_lot_equivalents(db: Session, symbol: str, user_id: int | None, base_lot: float, exclude_order_id: int | None = None) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    orders = _active_pending_orders(db, symbol, user_id, exclude_order_id=exclude_order_id)
    return sum(max(0.0, float(order.volume)) / safe_base for order in orders)


def bot_reserved_signal_lot_equivalents(db: Session, symbol: str, user_id: int | None, base_lot: float, exclude_signal_id: int | None = None) -> float:
    safe_base = base_lot if base_lot > 0 else 0.01
    total = 0.0
    for signal in _active_reserved_signals(db, symbol, user_id, exclude_signal_id=exclude_signal_id):
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
    pending_orders: Sequence[Order] | None = None,
    reserved_signals: Sequence[StrategySignal] | None = None,
) -> float:
    from app.risk.snapshot import candidate_loss

    total = 0.0
    orders = list(pending_orders) if pending_orders is not None else _active_pending_orders(
        db, symbol, user_id, exclude_order_id=exclude_order_id
    )
    signals = list(reserved_signals) if reserved_signals is not None else _active_reserved_signals(
        db, symbol, user_id, exclude_signal_id=exclude_signal_id
    )
    for order in orders:
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
    for signal in signals:
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
    account_login: int | None = None,
    account_server: str | None = None,
) -> BotExposurePlan:
    normalized_symbol = symbol.upper()
    base_lot = _base_lot(balance, trading_settings)
    ath = get_or_update_symbol_ath(db, normalized_symbol)
    zone = ath_zone_for_price_config(ath, current_price, strategy_params)
    configured_max_equivalents = int(_float_or_none((strategy_params or {}).get("max_equivalent_positions")) or 3)
    # ATH zones remain part of the visual/diagnostic context, but no longer
    # reduce or block Torum's operative capacity.  The only sizing ceiling is
    # the configured equivalent-position maximum.
    max_equivalents = max(1, configured_max_equivalents)

    execution_mode = str(getattr(trading_settings, "trading_mode", "")).upper() or None
    open_positions = bot_open_positions(
        db, normalized_symbol, user_id, mode=execution_mode,
        account_login=account_login, account_server=account_server,
    )
    pending_orders = _active_pending_orders(
        db, normalized_symbol, user_id, exclude_order_id=exclude_order_id,
        mode=execution_mode, account_login=account_login, account_server=account_server,
    )
    reserved_signals = _active_reserved_signals(
        db, normalized_symbol, user_id, exclude_signal_id=exclude_signal_id, mode=execution_mode,
    )
    # Once an Order exists it is the authoritative reservation. Its originating
    # signal may remain RISK_APPROVED/SENT/RECONCILING at the same time; counting
    # both would turn one x3 request into six occupied equivalents and block the
    # next valid setup. This also covers an exception before runner could copy
    # order.id back into signal.order_id by using Order.strategy_signal_id.
    pending_signal_ids = {
        int(order.strategy_signal_id)
        for order in pending_orders
        if order.strategy_signal_id is not None
    }
    reserved_signals = [
        signal
        for signal in reserved_signals
        if signal.id is None or int(signal.id) not in pending_signal_ids
    ]
    open_equiv = open_lot_equivalents(open_positions, base_lot)
    pending_equiv = sum(max(0.0, float(order.volume)) / base_lot for order in pending_orders)
    reserved_equiv = 0.0
    for signal in reserved_signals:
        metadata = signal.metadata_json or {}
        volume = _float_or_none(metadata.get("accepted_volume")) or _float_or_none(signal.suggested_volume)
        reserved_equiv += (max(0.0, volume) / base_lot) if volume is not None else max(0.0, _float_or_none(metadata.get("accepted_multiplier")) or _float_or_none(metadata.get("desired_multiplier")) or 1.0)
    used_equiv = open_equiv + pending_equiv + reserved_equiv
    max_multiplier = min(max(1, int(desired_multiplier)), configured_max_equivalents)

    if balance is None or balance <= 0:
        return _blocked("missing_account_balance", ath, zone, max_equivalents, open_equiv)
    if current_price is None or current_price <= 0:
        return _blocked("missing_current_price", ath, zone, max_equivalents, open_equiv)

    from app.risk.snapshot import RiskSnapshotService, candidate_loss

    # Never synchronously rebuild/calibrate the risk snapshot while an entry is
    # waiting. A dirty valid snapshot remains usable; when absent, the mapping
    # provides the deterministic contract/conversion values and current open
    # positions are already available in this transaction.
    snapshot = RiskSnapshotService(db).get_snapshot(
        normalized_symbol,
        source="STRATEGY",
        recompute_if_missing=False,
        schedule_recompute=False,
    )
    mapped_contract_size = float(symbol_mapping.contract_size) if symbol_mapping is not None and symbol_mapping.contract_size > 0 else 100.0
    mapped_conversion = float(symbol_mapping.risk_conversion_rate) if symbol_mapping is not None and symbol_mapping.risk_conversion_rate > 0 else 1.0
    contract_size = float(snapshot.contract_size) if snapshot.valid and snapshot.contract_size > 0 else mapped_contract_size * mapped_conversion
    stress_drop_pct = _float_or_none((strategy_params or {}).get("risk_stress_drop_from_ath_pct")) or (ATH_ADVERSE_MOVE_RATIO * 100.0)
    stress_price = ath * (1.0 - stress_drop_pct / 100.0) if ath is not None else None
    current_loss: float | None = None
    if stress_price is not None and stress_price > 0:
        current_loss = round(
            sum(
                candidate_loss(
                    side=position.side,
                    volume=float(position.volume),
                    price=float(position.open_price),
                    stress_price=stress_price,
                    contract_size=contract_size,
                )
                for position in open_positions
            ),
            2,
        )
        reserved_loss = bot_reserved_potential_loss(
            db,
            normalized_symbol,
            user_id,
            stress_price=stress_price,
            contract_size=contract_size,
            fallback_price=current_price,
            exclude_order_id=exclude_order_id,
            exclude_signal_id=exclude_signal_id,
            pending_orders=pending_orders,
            reserved_signals=reserved_signals,
        )
        current_loss = round(current_loss + reserved_loss, 2)

    # Degradation is deterministic and *only* capacity-based.  ATH colour and
    # stress loss stay diagnostic: they never reduce x3/x2/x1.  Convert the
    # remaining equivalent capacity to an integer slot count and fit the
    # multiplier requested by the support/Torum rectangle into that capacity.
    remaining_equiv = max(0.0, float(max_equivalents) - float(used_equiv))
    available_integer_slots = max(0, int(math.floor(remaining_equiv + 1e-9)))
    multiplier = min(max_multiplier, available_integer_slots)
    if multiplier >= 1:
        volume = round(base_lot * multiplier, 8)
        potential_loss: float | None = None
        projected_balance: float | None = None
        if current_loss is not None and stress_price is not None and stress_price > 0:
            added_loss = candidate_loss(
                side="BUY",
                volume=volume,
                price=current_price,
                stress_price=stress_price,
                contract_size=contract_size,
            )
            potential_loss = round(current_loss + added_loss, 2)
            projected_balance = round(balance - potential_loss, 2)
        return BotExposurePlan(
            allowed=True,
            multiplier=multiplier,
            volume=volume,
            reason="allowed_capacity_only",
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
        reason="equivalent_capacity_exceeded",
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

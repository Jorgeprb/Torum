from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class LotSizeCalculation:
    available_equity: float | None
    equity_per_0_01_lot: float
    base_lot: float
    multiplier: int
    effective_lot: float
    min_lot: float
    lot_step: float
    source: str


def calculate_lot_size(
    *,
    available_equity: float | None,
    equity_per_0_01_lot: float = 2500.0,
    minimum_lot: float = 0.01,
    lot_step: float = 0.01,
    multiplier: int = 1,
    enabled: bool = True,
) -> LotSizeCalculation:
    safe_multiplier = max(1, int(multiplier or 1))
    safe_step = lot_step if lot_step > 0 else 0.01
    safe_minimum = _round_to_step(max(minimum_lot, safe_step), safe_step)
    safe_equity_unit = equity_per_0_01_lot if equity_per_0_01_lot > 0 else 2500.0

    if not enabled:
        base_lot = safe_minimum
        source = "minimum_lot_lot_per_equity_disabled"
    elif available_equity is None or available_equity <= 0:
        base_lot = safe_minimum
        source = "minimum_lot_no_equity"
    else:
        calculated = floor(available_equity / safe_equity_unit) * 0.01
        base_lot = _round_to_step(max(calculated, safe_minimum), safe_step)
        source = "account_equity"

    effective_lot = _round_to_step(base_lot * safe_multiplier, safe_step)
    return LotSizeCalculation(
        available_equity=available_equity,
        equity_per_0_01_lot=safe_equity_unit,
        base_lot=base_lot,
        multiplier=safe_multiplier,
        effective_lot=effective_lot,
        min_lot=safe_minimum,
        lot_step=safe_step,
        source=source,
    )


def calculate_buy_take_profit(entry_price: float, take_profit_percent: float) -> float:
    return round(entry_price * (1 + take_profit_percent / 100), 8)


def _round_to_step(value: float, step: float) -> float:
    rounded = round(value / step) * step
    return round(rounded, 8)

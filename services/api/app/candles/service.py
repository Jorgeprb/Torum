from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.candles.models import Candle
from app.candles.schemas import CandleRead, CandleRow
from app.core.config import get_settings
from app.market_data.timeframes import SUPPORTED_TIMEFRAMES, Timeframe, bucket_start, ensure_utc

TickPriceSource = str


def normalized_price_source(price_source: TickPriceSource) -> str:
    normalized = price_source.strip().upper().replace("-", "_")
    if normalized in {"LAST_OR_MID", "MID", "BID", "ASK", "LAST"}:
        return normalized
    return "BID"


def select_tick_price(tick: dict[str, object], price_source: TickPriceSource = "BID") -> float | None:
    source = normalized_price_source(price_source)
    last = tick.get("last")
    bid = tick.get("bid")
    ask = tick.get("ask")

    if source == "BID" and isinstance(bid, (int, float)) and bid > 0:
        return float(bid)
    if source == "ASK" and isinstance(ask, (int, float)) and ask > 0:
        return float(ask)
    if source in {"LAST", "LAST_OR_MID"} and isinstance(last, (int, float)) and last > 0:
        return float(last)
    if source in {"MID", "LAST_OR_MID"} and isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2
    if isinstance(last, (int, float)) and last > 0:
        return float(last)
    if isinstance(bid, (int, float)) and bid > 0:
        return float(bid)
    if isinstance(ask, (int, float)) and ask > 0:
        return float(ask)
    return None


def build_candle_rows_from_ticks(
    ticks: Sequence[dict[str, object]],
    timeframes: Iterable[Timeframe] = SUPPORTED_TIMEFRAMES,
    price_source: TickPriceSource = "BID",
) -> list[dict[str, object]]:
    buckets: dict[tuple[str, Timeframe, datetime], dict[str, object]] = {}

    sorted_ticks = sorted(ticks, key=lambda tick: ensure_utc(tick["time"]))  # type: ignore[arg-type]
    for tick in sorted_ticks:
        price = select_tick_price(tick, price_source)
        if price is None:
            continue

        symbol = str(tick["internal_symbol"])
        tick_time = ensure_utc(tick["time"])  # type: ignore[arg-type]
        volume = tick.get("volume")
        tick_volume = float(volume) if isinstance(volume, (int, float)) else 0.0

        for timeframe in timeframes:
            bucket = bucket_start(tick_time, timeframe)
            key = (symbol, timeframe, bucket)
            candle = buckets.get(key)
            if candle is None:
                buckets[key] = {
                    "time": bucket,
                    "internal_symbol": symbol,
                    "timeframe": timeframe,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": tick_volume,
                    "tick_count": 1,
                    "source": "TICK_AGGREGATOR",
                }
                continue

            candle["high"] = max(float(candle["high"]), price)
            candle["low"] = min(float(candle["low"]), price)
            candle["close"] = price
            candle["volume"] = float(candle["volume"]) + tick_volume
            candle["tick_count"] = int(candle["tick_count"]) + 1

    return [CandleRow.model_validate(row).model_dump() for row in buckets.values()]


def merge_candle_values(existing: dict[str, object], update: dict[str, object]) -> dict[str, object]:
    return {
        **existing,
        "high": max(float(existing["high"]), float(update["high"])),
        "low": min(float(existing["low"]), float(update["low"])),
        "close": float(update["close"]),
        "volume": float(existing.get("volume") or 0) + float(update.get("volume") or 0),
        "tick_count": int(existing.get("tick_count") or 0) + int(update.get("tick_count") or 0),
    }


def candle_to_read(candle: Candle) -> CandleRead:
    settings = get_settings()
    return CandleRead(
        time=int(ensure_utc(candle.time).timestamp()),
        internal_symbol=candle.internal_symbol,
        timeframe=candle.timeframe,  # type: ignore[arg-type]
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        tick_count=candle.tick_count,
        source=candle.source,
        price_source=normalized_price_source(settings.candle_price_source),
    )


class CandleAggregator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def aggregate_ticks(self, ticks: Sequence[dict[str, object]]) -> list[Candle]:
        settings = get_settings()
        candle_rows = build_candle_rows_from_ticks(
            ticks=ticks,
            timeframes=SUPPORTED_TIMEFRAMES,
            price_source=settings.candle_price_source,
        )
        if not candle_rows:
            return []

        stmt = pg_insert(Candle).values(candle_rows)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[Candle.internal_symbol, Candle.timeframe, Candle.time],
            set_={
                "high": func.greatest(Candle.high, excluded.high),
                "low": func.least(Candle.low, excluded.low),
                "close": excluded.close,
                "volume": func.coalesce(Candle.volume, 0.0) + func.coalesce(excluded.volume, 0.0),
                "tick_count": func.coalesce(Candle.tick_count, 0) + func.coalesce(excluded.tick_count, 0),
                "source": excluded.source,
                "updated_at": func.now(),
            },
        )
        self.db.execute(stmt)

        keys = [(row["internal_symbol"], row["timeframe"], row["time"]) for row in candle_rows]
        return list(
            self.db.scalars(
                select(Candle)
                .where(tuple_(Candle.internal_symbol, Candle.timeframe, Candle.time).in_(keys))
                .order_by(Candle.internal_symbol, Candle.timeframe, Candle.time)
            )
        )

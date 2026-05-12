from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Timeframe = Literal["M1", "M5", "H1", "H2", "H3", "H4", "D1", "W1"]

SUPPORTED_TIMEFRAMES: tuple[Timeframe, ...] = ("M1", "M5", "H1", "H2", "H3", "H4", "D1", "W1")
MADRID_TZ = ZoneInfo("Europe/Madrid")
MADRID_ALIGNED_H3_SYMBOLS = {"XAUUSD", "XAUEUR"}


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def bucket_start(value: datetime, timeframe: Timeframe, symbol: str | None = None) -> datetime:
    dt = ensure_utc(value)

    if timeframe == "M1":
        return dt.replace(second=0, microsecond=0)
    if timeframe == "M5":
        minute = dt.minute - (dt.minute % 5)
        return dt.replace(minute=minute, second=0, microsecond=0)
    if timeframe == "H1":
        return dt.replace(minute=0, second=0, microsecond=0)
    if timeframe == "H2":
        hour = dt.hour - (dt.hour % 2)
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    if timeframe == "H3":
        if symbol is not None and symbol.upper() in MADRID_ALIGNED_H3_SYMBOLS:
            local_dt = dt.astimezone(MADRID_TZ)
            local_hour = local_dt.hour - (local_dt.hour % 3)
            local_bucket = local_dt.replace(hour=local_hour, minute=0, second=0, microsecond=0)
            return local_bucket.astimezone(UTC)
        hour = dt.hour - (dt.hour % 3)
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    if timeframe == "H4":
        hour = dt.hour - (dt.hour % 4)
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    if timeframe == "D1":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if timeframe == "W1":
        start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=start_of_day.weekday())

    raise ValueError(f"Unsupported timeframe: {timeframe}")

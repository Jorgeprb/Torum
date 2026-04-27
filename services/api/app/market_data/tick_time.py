from datetime import datetime

from app.market_data.timeframes import ensure_utc


def tick_time_msc_from_datetime(value: datetime) -> int:
    tick_time = ensure_utc(value)
    return int(tick_time.timestamp() * 1000)


from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def broker_chart_datetime(value: datetime) -> datetime:
    """Convert real UTC into the pseudo-UTC clock used by broker chart rows.

    MT5 rows in this project intentionally retain broker wall-clock values while
    being stored in timezone-aware columns.  Torum therefore has to compare
    those rows against the same chart clock, not against real UTC.  Returning a
    UTC-tagged wall clock keeps existing database/chart semantics intact.
    """

    checked = ensure_utc(value)
    try:
        broker_zone = ZoneInfo(get_settings().chart_broker_time_zone)
    except Exception:
        broker_zone = ZoneInfo("Etc/GMT-3")
    return checked.astimezone(broker_zone).replace(tzinfo=UTC)


def resolve_market_clock(
    real_now: datetime,
    observed_market_time: datetime | None,
    *,
    tolerance_seconds: float = 600.0,
) -> tuple[datetime, str]:
    """Choose the clock domain that best matches the latest market timestamp.

    Tests/imports and non-MT5 sources may use canonical UTC, while the live MT5
    stream uses broker chart wall time.  Selecting the closest clock avoids
    hard-coding one domain and prevents stale candles from being mistaken for
    the latest closed M5 candle.
    """

    real_utc = ensure_utc(real_now)
    if observed_market_time is None:
        return real_utc, "UTC"

    observed = ensure_utc(observed_market_time)
    chart_now = broker_chart_datetime(real_utc)
    real_distance = abs((observed - real_utc).total_seconds())
    chart_distance = abs((observed - chart_now).total_seconds())

    if chart_distance <= tolerance_seconds and chart_distance + 1.0 < real_distance:
        return chart_now, "BROKER_CHART"
    if real_distance <= tolerance_seconds:
        return real_utc, "UTC"

    # A just-received live tick should be close to one of the two clocks.  When
    # it is not, prefer the domain closest to the data but keep the decision
    # explicit in diagnostics rather than silently mixing both clocks.
    if chart_distance < real_distance:
        return chart_now, "BROKER_CHART_INFERRED"
    return real_utc, "UTC_INFERRED"

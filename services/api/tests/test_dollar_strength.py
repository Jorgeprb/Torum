from datetime import UTC, datetime, timedelta

from app.market_context.dollar_strength import classify_dollar_strength


def _dxy_rows(last_close: float, *, last_open: float | None = None, days: int = 35, start: float = 100.0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base_time = datetime(2026, 4, 1, tzinfo=UTC)
    for index in range(days - 1):
        close = start
        rows.append({"time": base_time + timedelta(days=index), "open": close, "high": close + 0.2, "low": close - 0.2, "close": close})
    rows.append(
        {
            "time": base_time + timedelta(days=days - 1),
            "open": last_open if last_open is not None else last_close,
            "high": max(last_open if last_open is not None else last_close, last_close) + 0.2,
            "low": min(last_open if last_open is not None else last_close, last_close) - 0.2,
            "close": last_close,
        }
    )
    return rows


def test_dxy_below_sma30_allows_trading() -> None:
    snapshot = classify_dollar_strength(_dxy_rows(99.0), params={"usd_neutral_band_points": 0.1})

    assert snapshot.state == "WEAK"
    assert snapshot.trading_allowed is True
    assert snapshot.reason == "dxy_below_sma30"


def test_dxy_above_sma30_blocks_trading() -> None:
    snapshot = classify_dollar_strength(_dxy_rows(101.0), params={"usd_neutral_band_points": 0.1})

    assert snapshot.state == "STRONG"
    assert snapshot.trading_allowed is False
    assert snapshot.reason == "dxy_above_sma30"


def test_dxy_strong_drop_override_allows_trading() -> None:
    base_time = datetime(2026, 4, 1, tzinfo=UTC)
    closes = [100.0] * 31 + [102.0, 102.0, 101.5, 101.0]
    rows = [
        {"time": base_time + timedelta(days=index), "open": close + (1 if index == len(closes) - 1 else 0), "high": close + 0.2, "low": close - 0.2, "close": close}
        for index, close in enumerate(closes)
    ]

    snapshot = classify_dollar_strength(
        rows,
        params={
            "usd_neutral_band_points": 0.1,
            "usd_strong_drop_lookback_days": 3,
            "usd_strong_drop_min_pct": 0.45,
            "usd_strong_drop_require_bearish_close": True,
        },
    )

    assert snapshot.state == "WEAK"
    assert snapshot.trading_allowed is True
    assert snapshot.strong_drop_override_active is True
    assert snapshot.reason == "dxy_above_sma30_but_falling_strongly"


def test_missing_dxy_symbols_strict_blocks_bot() -> None:
    snapshot = classify_dollar_strength([], params={"usd_strength_strict": True}, missing_symbols=["EURUSD"])

    assert snapshot.state == "UNKNOWN"
    assert snapshot.trading_allowed is False
    assert snapshot.reason == "usd_strength_unknown"

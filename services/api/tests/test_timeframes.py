from datetime import UTC, datetime

from app.market_data.timeframes import bucket_start


def test_bucket_m1_truncates_to_minute() -> None:
    value = datetime(2026, 4, 26, 12, 34, 56, 123000, tzinfo=UTC)

    assert bucket_start(value, "M1") == datetime(2026, 4, 26, 12, 34, tzinfo=UTC)


def test_bucket_m5_uses_previous_multiple_of_five() -> None:
    value = datetime(2026, 4, 26, 12, 34, 56, tzinfo=UTC)

    assert bucket_start(value, "M5") == datetime(2026, 4, 26, 12, 30, tzinfo=UTC)


def test_bucket_h2_and_h4_use_hour_multiples() -> None:
    value = datetime(2026, 4, 26, 13, 45, 10, tzinfo=UTC)

    assert bucket_start(value, "H2") == datetime(2026, 4, 26, 12, tzinfo=UTC)
    assert bucket_start(value, "H3") == datetime(2026, 4, 26, 12, tzinfo=UTC)
    assert bucket_start(value, "H4") == datetime(2026, 4, 26, 12, tzinfo=UTC)


def test_bucket_d1_and_w1_start_at_utc_boundaries() -> None:
    value = datetime(2026, 4, 26, 13, 45, 10, tzinfo=UTC)

    assert bucket_start(value, "D1") == datetime(2026, 4, 26, tzinfo=UTC)
    assert bucket_start(value, "W1") == datetime(2026, 4, 20, tzinfo=UTC)

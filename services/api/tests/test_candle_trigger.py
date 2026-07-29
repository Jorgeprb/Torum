from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.strategies.candle_trigger import clear_candle_trigger_state, symbols_with_newly_closed_m5


def _candle(symbol: str, timeframe: str, when: datetime):
    return SimpleNamespace(internal_symbol=symbol, timeframe=timeframe, time=when)


def test_candle_trigger_runs_once_on_start_and_on_bucket_advance() -> None:
    clear_candle_trigger_state()
    bucket = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    assert symbols_with_newly_closed_m5([_candle("XAUUSD", "M5", bucket)]) == ["XAUUSD"]
    assert symbols_with_newly_closed_m5([_candle("XAUUSD", "M5", bucket)]) == []
    assert symbols_with_newly_closed_m5([_candle("XAUUSD", "M5", bucket + timedelta(minutes=5))]) == ["XAUUSD"]


def test_candle_trigger_ignores_non_m5() -> None:
    clear_candle_trigger_state()
    assert symbols_with_newly_closed_m5([_candle("XAUUSD", "M1", datetime.now(UTC))]) == []

from types import SimpleNamespace

from bridge.symbol_mapper import SymbolMapping
from bridge.tick_collector import TickDeduplicator, mt5_tick_to_torum


def test_mt5_tick_to_torum_uses_time_msc_and_null_last() -> None:
    mapping = SymbolMapping(internal_symbol="XAUUSD", broker_symbol="XAUUSD", display_name="Gold / USD")
    raw_tick = SimpleNamespace(time=1777204800, time_msc=1777204800123, bid=2325.12, ask=2325.34, last=0.0, volume=0)

    tick = mt5_tick_to_torum(raw_tick, mapping)

    assert tick is not None
    assert tick["internal_symbol"] == "XAUUSD"
    assert tick["broker_symbol"] == "XAUUSD"
    assert tick["time"] == "2026-04-26T12:00:00.123000Z"
    assert tick["bid"] == 2325.12
    assert tick["ask"] == 2325.34
    assert tick["last"] is None


def test_tick_deduplicator_rejects_same_tick_key() -> None:
    deduplicator = TickDeduplicator()
    tick = {
        "internal_symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "time": "2026-04-26T12:00:00.123Z",
        "bid": 2325.12,
        "ask": 2325.34,
        "last": None,
    }

    assert deduplicator.is_new(tick)
    assert not deduplicator.is_new(tick)

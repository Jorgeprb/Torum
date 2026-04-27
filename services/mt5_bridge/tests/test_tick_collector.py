from types import SimpleNamespace

from bridge.symbol_mapper import SymbolMapping
from bridge.tick_collector import TickCollector, TickDeduplicator, mt5_tick_to_torum


def test_mt5_tick_to_torum_uses_time_msc_and_null_last() -> None:
    mapping = SymbolMapping(internal_symbol="XAUUSD", broker_symbol="XAUUSD", display_name="Gold / USD")
    raw_tick = SimpleNamespace(time=1777204800, time_msc=1777204800123, bid=2325.12, ask=2325.34, last=0.0, volume=0)

    tick = mt5_tick_to_torum(raw_tick, mapping)

    assert tick is not None
    assert tick["internal_symbol"] == "XAUUSD"
    assert tick["broker_symbol"] == "XAUUSD"
    assert tick["time"] == "2026-04-26T12:00:00.123000Z"
    assert tick["time_msc"] == 1777204800123
    assert tick["bid"] == 2325.12
    assert tick["ask"] == 2325.34
    assert tick["last"] is None


def test_tick_deduplicator_rejects_same_tick_key() -> None:
    deduplicator = TickDeduplicator()
    tick = {
        "internal_symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "time": "2026-04-26T12:00:00.123Z",
        "time_msc": 1777204800123,
        "bid": 2325.12,
        "ask": 2325.34,
        "last": None,
    }

    assert deduplicator.is_new(tick)
    assert not deduplicator.is_new(tick)


class _FakeSettings:
    mt5_diagnostic_log_interval_seconds = 5


class _FakeMT5Client:
    def get_ticks_since(self, broker_symbol, since_datetime):  # type: ignore[no-untyped-def]
        return [
            SimpleNamespace(
                time=1777204800,
                time_msc=1777204800100,
                bid=4671.0,
                ask=4671.2,
                last=0.0,
                volume=0,
            )
        ]

    def get_latest_tick(self, broker_symbol):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            time=1777204800,
            time_msc=1777204800646,
            bid=4672.08,
            ask=4672.23,
            last=0.0,
            volume=0,
        )


class _FakeTickBuffer:
    def __init__(self) -> None:
        self.ticks = []

    def add_many(self, ticks):  # type: ignore[no-untyped-def]
        self.ticks.extend(ticks)
        return 0


def test_collector_includes_symbol_info_tick_snapshot_after_range_ticks() -> None:
    mapping = SymbolMapping(internal_symbol="XAUUSD", broker_symbol="XAUUSD", display_name="Gold / USD")
    tick_buffer = _FakeTickBuffer()
    collector = TickCollector(_FakeSettings(), _FakeMT5Client(), object(), tick_buffer)  # type: ignore[arg-type]

    collector._collect_symbol(mapping, since=SimpleNamespace())  # type: ignore[arg-type]

    assert len(tick_buffer.ticks) == 2
    assert tick_buffer.ticks[-1]["time_msc"] == 1777204800646
    assert tick_buffer.ticks[-1]["bid"] == 4672.08
    assert tick_buffer.ticks[-1]["ask"] == 4672.23

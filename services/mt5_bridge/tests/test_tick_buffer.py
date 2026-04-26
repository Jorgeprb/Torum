from bridge.tick_buffer import TickBuffer


class FakeBackendClient:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, object]]] = []

    def post_ticks_batch(self, ticks: list[dict[str, object]], account: dict[str, object] | None, source: str) -> dict[str, int]:
        self.batches.append(ticks)
        return {
            "received": len(ticks),
            "inserted": len(ticks),
            "duplicates_ignored": 0,
            "candles_updated": len(ticks),
        }


def test_tick_buffer_flushes_by_size() -> None:
    backend = FakeBackendClient()
    buffer = TickBuffer(backend, batch_max_size=2, flush_interval_seconds=60, max_buffer_size=10)  # type: ignore[arg-type]

    buffer.add_many([{"id": 1}, {"id": 2}])
    result = buffer.flush(account=None)

    assert result.submitted == 2
    assert result.inserted == 2
    assert buffer.size == 0
    assert len(backend.batches) == 1


def test_tick_buffer_drops_oldest_when_full() -> None:
    backend = FakeBackendClient()
    buffer = TickBuffer(backend, batch_max_size=10, flush_interval_seconds=60, max_buffer_size=2)  # type: ignore[arg-type]

    dropped = buffer.add_many([{"id": 1}, {"id": 2}, {"id": 3}])

    assert dropped == 1
    assert buffer.size == 2

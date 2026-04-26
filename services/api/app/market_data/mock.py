import asyncio
from datetime import UTC, datetime
import logging
import random

from pydantic import BaseModel

from app.candles.service import candle_to_read
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.symbols.models import SymbolMapping
from app.ticks.schemas import TickBatchRequest, TickInput
from app.ticks.service import ingest_tick_batch
from app.websockets.manager import market_ws_manager

logger = logging.getLogger(__name__)


class MockMarketStatus(BaseModel):
    running: bool
    source: str = "MOCK"
    last_tick_time: datetime | None = None
    interval_seconds: float
    symbols: list[str]


class MockMarketService:
    def __init__(self) -> None:
        settings = get_settings()
        self.interval_seconds = settings.mock_market_tick_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._last_tick_time: datetime | None = None
        self._prices: dict[str, float] = {
            "XAUUSD": 2325.0,
            "XAUEUR": 2180.0,
            "XAUAUD": 3540.0,
            "XAUJPY": 362000.0,
        }

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> MockMarketStatus:
        if not self.running:
            self._task = asyncio.create_task(self._run(), name="torum-mock-market")
            logger.info("Mock market data started")
        return self.status()

    async def stop(self) -> MockMarketStatus:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("Mock market data stopped")
        self._task = None
        await market_ws_manager.broadcast_market_status(False, "MOCK", self._last_tick_time)
        return self.status()

    def status(self) -> MockMarketStatus:
        return MockMarketStatus(
            running=self.running,
            last_tick_time=self._last_tick_time,
            interval_seconds=self.interval_seconds,
            symbols=sorted(self._prices),
        )

    async def _run(self) -> None:
        while True:
            try:
                await self._publish_mock_ticks()
            except Exception:
                logger.exception("Mock market data cycle failed")
            await asyncio.sleep(self.interval_seconds)

    async def _publish_mock_ticks(self) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            mappings = db.query(SymbolMapping).filter(SymbolMapping.enabled.is_(True)).all()
            ticks = [self._build_tick(mapping, now) for mapping in mappings]
            if not ticks:
                return

            received_ticks, inserted_ticks, candles, _inserted_rows = ingest_tick_batch(
                db,
                TickBatchRequest(source="MOCK", ticks=ticks),
            )

        self._last_tick_time = now
        logger.debug(
            "Mock market emitted %s ticks, inserted %s and updated %s candles",
            received_ticks,
            inserted_ticks,
            len(candles),
        )
        for candle in candles:
            await market_ws_manager.broadcast_candle_update(candle_to_read(candle).model_dump())
        await market_ws_manager.broadcast_market_status(True, "MOCK", self._last_tick_time)

    def _build_tick(self, mapping: SymbolMapping, now: datetime) -> TickInput:
        base_price = self._prices.setdefault(mapping.internal_symbol, 2325.0)
        step = max(mapping.point, base_price * 0.00005)
        drift = random.uniform(-step, step)
        next_price = max(mapping.point, base_price + drift)
        self._prices[mapping.internal_symbol] = next_price

        spread = max(mapping.point * 2, next_price * 0.00004)
        bid = round(next_price - spread / 2, mapping.digits)
        ask = round(next_price + spread / 2, mapping.digits)
        last = round(next_price, mapping.digits)

        return TickInput(
            internal_symbol=mapping.internal_symbol,
            broker_symbol=mapping.broker_symbol,
            time=now,
            bid=bid,
            ask=ask,
            last=last,
            volume=0.0,
            source="MOCK",
        )

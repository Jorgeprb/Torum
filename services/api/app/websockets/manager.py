from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.core.distributed_state import distributed_state
from app.market_data.tick_time import tick_time_msc_from_datetime

logger = logging.getLogger(__name__)
_REDIS_CHANNEL = "market-events"


class MarketWebSocketManager:
    """Local WebSocket fan-out with optional Redis replication between API workers."""

    def __init__(self) -> None:
        self._connections: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._send_timeout_seconds = 2.0
        self._instance_id = uuid.uuid4().hex
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscriber_stop = threading.Event()
        self._subscriber_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._subscriber_thread is not None and self._subscriber_thread.is_alive():
            return
        self._loop = asyncio.get_running_loop()
        self._subscriber_stop.clear()
        self._subscriber_thread = threading.Thread(
            target=distributed_state.consume_json,
            args=(_REDIS_CHANNEL, self._subscriber_stop, self._handle_remote_from_thread),
            daemon=True,
            name="torum-websocket-redis-subscriber",
        )
        self._subscriber_thread.start()

    def stop(self) -> None:
        self._subscriber_stop.set()
        thread = self._subscriber_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._subscriber_thread = None
        self._loop = None

    async def connect(self, websocket: WebSocket, symbol: str, timeframe: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[(symbol, timeframe)].add(websocket)

    async def disconnect(self, websocket: WebSocket, symbol: str, timeframe: str) -> None:
        async with self._lock:
            connections = self._connections.get((symbol, timeframe))
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop((symbol, timeframe), None)

    async def broadcast_candle_update(self, candle: dict[str, Any]) -> None:
        symbol = str(candle["internal_symbol"])
        timeframe = str(candle["timeframe"])
        await self._broadcast(
            scope="channel",
            symbol=symbol,
            timeframe=timeframe,
            message={"type": "candle_update", "symbol": symbol, "timeframe": timeframe, "candle": candle},
        )

    async def broadcast_market_status(self, connected: bool, source: str, last_tick_time: datetime | None) -> None:
        await self._broadcast(
            scope="all",
            message={
                "type": "market_status",
                "connected": connected,
                "source": source,
                "last_tick_time": last_tick_time.isoformat() if last_tick_time else None,
            },
        )

    async def broadcast_market_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(tick["internal_symbol"])
        tick_time = tick.get("time")
        time_msc = tick.get("time_msc")
        if time_msc is None and isinstance(tick_time, datetime):
            time_msc = tick_time_msc_from_datetime(tick_time)
        bid = tick.get("bid")
        ask = tick.get("ask")
        mid = (float(bid) + float(ask)) / 2 if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
        spread = float(ask) - float(bid) if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
        await self._broadcast(
            scope="symbol",
            symbol=symbol,
            message={
                "type": "latest_tick_update",
                "symbol": symbol,
                "broker_symbol": tick.get("broker_symbol"),
                "time": tick_time.isoformat() if isinstance(tick_time, datetime) else tick_time,
                "time_msc": time_msc,
                "bid": bid,
                "ask": ask,
                "last": tick.get("last"),
                "mid": mid,
                "spread": spread,
                "volume": tick.get("volume"),
                "source": tick.get("source"),
            },
        )

    async def broadcast_price_alert_triggered(self, event: dict[str, Any]) -> None:
        symbol = str(event["symbol"])
        await self._broadcast(scope="symbol", symbol=symbol, message={**event, "type": "price_alert_triggered"})

    async def broadcast_price_alert_updated(self, symbol: str, alert_id: str) -> None:
        await self._broadcast(
            scope="symbol",
            symbol=symbol,
            message={"type": "price_alert_updated", "alert_id": alert_id, "symbol": symbol},
        )

    async def broadcast_position_event(self, message: dict[str, Any]) -> None:
        await self._broadcast(scope="all", message=message)

    async def _broadcast(
        self,
        *,
        scope: str,
        message: dict[str, Any],
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> None:
        envelope = {
            "origin": self._instance_id,
            "scope": scope,
            "symbol": symbol,
            "timeframe": timeframe,
            "message": message,
        }
        await self._fanout_envelope(envelope)
        distributed_state.publish_json(_REDIS_CHANNEL, envelope)

    def _handle_remote_from_thread(self, envelope: Any) -> None:
        if not isinstance(envelope, dict) or envelope.get("origin") == self._instance_id:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._fanout_envelope(envelope), loop)

    async def _fanout_envelope(self, envelope: dict[str, Any]) -> None:
        message = envelope.get("message")
        if not isinstance(message, dict):
            return
        scope = str(envelope.get("scope") or "all")
        symbol = envelope.get("symbol")
        timeframe = envelope.get("timeframe")
        if scope == "channel" and isinstance(symbol, str) and isinstance(timeframe, str):
            await self._send_to_channel(symbol, timeframe, message)
            return
        if scope == "symbol" and isinstance(symbol, str):
            for channel_symbol, channel_timeframe in await self._channel_keys(symbol=symbol):
                await self._send_to_channel(channel_symbol, channel_timeframe, message)
            return
        for channel_symbol, channel_timeframe in await self._channel_keys():
            await self._send_to_channel(channel_symbol, channel_timeframe, message)

    async def _channel_keys(self, *, symbol: str | None = None) -> list[tuple[str, str]]:
        async with self._lock:
            keys = list(self._connections)
        return [key for key in keys if symbol is None or key[0] == symbol]

    async def _send_to_channel(self, symbol: str, timeframe: str, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get((symbol, timeframe), set()))
        if not connections:
            return

        async def send_one(websocket: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=self._send_timeout_seconds)
                return None
            except Exception as exc:  # noqa: BLE001 - socket boundary
                logger.debug("Removing dead/slow websocket for %s/%s: %s", symbol, timeframe, exc)
                return websocket

        dead = [socket for socket in await asyncio.gather(*(send_one(socket) for socket in connections)) if socket]
        for websocket in dead:
            await self.disconnect(websocket, symbol, timeframe)


market_ws_manager = MarketWebSocketManager()

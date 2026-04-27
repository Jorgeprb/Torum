from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket


class MarketWebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, symbol: str, timeframe: str) -> None:
        await websocket.accept()
        self._connections[(symbol, timeframe)].add(websocket)

    def disconnect(self, websocket: WebSocket, symbol: str, timeframe: str) -> None:
        connections = self._connections.get((symbol, timeframe))
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop((symbol, timeframe), None)

    async def broadcast_candle_update(self, candle: dict[str, Any]) -> None:
        symbol = str(candle["internal_symbol"])
        timeframe = str(candle["timeframe"])
        message = {
            "type": "candle_update",
            "symbol": symbol,
            "timeframe": timeframe,
            "candle": candle,
        }
        await self._send_to_channel(symbol, timeframe, message)

    async def broadcast_market_status(
        self,
        connected: bool,
        source: str,
        last_tick_time: datetime | None,
    ) -> None:
        message = {
            "type": "market_status",
            "connected": connected,
            "source": source,
            "last_tick_time": last_tick_time.isoformat() if last_tick_time else None,
        }
        for key in list(self._connections):
            await self._send_to_channel(key[0], key[1], message)

    async def broadcast_market_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(tick["internal_symbol"])
        tick_time = tick.get("time")
        bid = tick.get("bid")
        ask = tick.get("ask")
        mid = (float(bid) + float(ask)) / 2 if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
        spread = float(ask) - float(bid) if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
        message = {
            "type": "latest_tick_update",
            "symbol": symbol,
            "broker_symbol": tick.get("broker_symbol"),
            "time": tick_time.isoformat() if isinstance(tick_time, datetime) else tick_time,
            "bid": bid,
            "ask": ask,
            "last": tick.get("last"),
            "mid": mid,
            "spread": spread,
            "volume": tick.get("volume"),
            "source": tick.get("source"),
        }
        for key in list(self._connections):
            if key[0] == symbol:
                await self._send_to_channel(key[0], key[1], message)

    async def broadcast_price_alert_triggered(self, event: dict[str, Any]) -> None:
        symbol = str(event["symbol"])
        message = dict(event)
        message["type"] = "price_alert_triggered"
        for key in list(self._connections):
            if key[0] == symbol:
                await self._send_to_channel(key[0], key[1], message)

    async def broadcast_price_alert_updated(self, symbol: str, alert_id: str) -> None:
        message = {
            "type": "price_alert_updated",
            "alert_id": alert_id,
            "symbol": symbol,
        }
        for key in list(self._connections):
            if key[0] == symbol:
                await self._send_to_channel(key[0], key[1], message)

    async def _send_to_channel(self, symbol: str, timeframe: str, message: dict[str, Any]) -> None:
        connections = list(self._connections.get((symbol, timeframe), set()))
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except RuntimeError:
                self.disconnect(websocket, symbol, timeframe)


market_ws_manager = MarketWebSocketManager()

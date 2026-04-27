from datetime import UTC, datetime
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.market_data.timeframes import SUPPORTED_TIMEFRAMES
from app.websockets.manager import market_ws_manager

router = APIRouter(tags=["websockets"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/market/{symbol}/{timeframe}")
async def market_stream(websocket: WebSocket, symbol: str, timeframe: str) -> None:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        await websocket.close(code=1008)
        return

    await market_ws_manager.connect(websocket, symbol, timeframe)
    await websocket.send_json(
        {
            "type": "market_status",
            "connected": True,
            "source": "MOCK",
            "last_tick_time": None,
        }
    )
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "ts": message.get("ts"),
                        "server_time": datetime.now(UTC).isoformat(),
                    }
                )
    except WebSocketDisconnect:
        market_ws_manager.disconnect(websocket, symbol, timeframe)
    except RuntimeError:
        market_ws_manager.disconnect(websocket, symbol, timeframe)
    except Exception as exc:
        logger.warning("Market websocket closed after unexpected error: %s", exc)
        market_ws_manager.disconnect(websocket, symbol, timeframe)

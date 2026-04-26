from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.market_data.timeframes import SUPPORTED_TIMEFRAMES
from app.websockets.manager import market_ws_manager

router = APIRouter(tags=["websockets"])


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
            await websocket.receive_text()
    except WebSocketDisconnect:
        market_ws_manager.disconnect(websocket, symbol, timeframe)

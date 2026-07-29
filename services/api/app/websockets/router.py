from datetime import UTC, datetime
import json
import logging

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.auth.security import decode_access_token
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.market_data.timeframes import SUPPORTED_TIMEFRAMES
from app.users.service import get_user_by_username
from app.websockets.manager import market_ws_manager

router = APIRouter(tags=["websockets"])
logger = logging.getLogger(__name__)


def _websocket_user_is_valid(token: str | None) -> bool:
    settings = get_settings()
    if not token and settings.environment.lower() == "test" and not settings.internal_auth_required:
        return True
    if not token:
        return False
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return False
    username = payload.get("sub")
    if not isinstance(username, str):
        return False
    with SessionLocal() as db:
        user = get_user_by_username(db, username)
        return bool(user is not None and user.is_active)


@router.websocket("/ws/market/{symbol}/{timeframe}")
async def market_stream(websocket: WebSocket, symbol: str, timeframe: str) -> None:
    token = websocket.query_params.get("token")
    if not _websocket_user_is_valid(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    normalized_symbol = symbol.upper()
    normalized_timeframe = timeframe.upper()
    if normalized_timeframe not in SUPPORTED_TIMEFRAMES:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await market_ws_manager.connect(websocket, normalized_symbol, normalized_timeframe)
    await websocket.send_json(
        {"type": "market_status", "connected": True, "source": "API", "last_tick_time": None}
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
                    {"type": "pong", "ts": message.get("ts"), "server_time": datetime.now(UTC).isoformat()}
                )
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass
    except Exception as exc:  # noqa: BLE001 - socket boundary
        logger.warning("Market websocket closed after unexpected error: %s", exc)
    finally:
        await market_ws_manager.disconnect(websocket, normalized_symbol, normalized_timeframe)

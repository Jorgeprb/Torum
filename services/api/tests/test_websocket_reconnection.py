from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.websockets.router import router as websocket_router


def test_market_websocket_replies_to_ping() -> None:
    app = FastAPI()
    app.include_router(websocket_router)

    with TestClient(app).websocket_connect("/ws/market/XAUUSD/M1") as websocket:
        status = websocket.receive_json()
        assert status["type"] == "market_status"

        websocket.send_json({"type": "ping", "ts": 123})
        pong = websocket.receive_json()

        assert pong["type"] == "pong"
        assert pong["ts"] == 123
        assert "server_time" in pong

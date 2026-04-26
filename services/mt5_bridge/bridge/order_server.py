import logging
from threading import Thread

import uvicorn
from fastapi import FastAPI

from bridge.account_state import AccountState
from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client
from bridge.order_executor import OrderExecutor
from bridge.order_models import BridgeOrderResponse, ClosePositionRequest, MarketOrderRequest

logger = logging.getLogger(__name__)


def create_order_app(settings: BridgeSettings, mt5_client: MT5Client) -> FastAPI:
    app = FastAPI(title="Torum MT5 Bridge", version="0.4.0")
    executor = OrderExecutor(settings, mt5_client)

    @app.get("/health")
    def health() -> dict[str, object]:
        connected = mt5_client.is_connected()
        account_payload = None
        try:
            account_payload = mt5_client.get_account_state().to_payload()
        except Exception:
            account_payload = None
        return {
            "ok": True,
            "connected_to_mt5": connected,
            "order_execution_enabled": settings.mt5_allow_order_execution,
            "market_data_only": settings.mt5_market_data_only,
            "account": account_payload,
        }

    @app.get("/account")
    def account() -> dict[str, object]:
        return mt5_client.get_account_state().to_payload()

    @app.get("/positions")
    def positions() -> list[dict[str, object]]:
        mt5 = mt5_client.mt5
        if mt5 is None:
            return []
        mt5_positions = mt5.positions_get()
        if mt5_positions is None:
            return []
        return [position._asdict() if hasattr(position, "_asdict") else dict(position) for position in mt5_positions]

    @app.post("/orders/market", response_model=BridgeOrderResponse)
    def market_order(payload: MarketOrderRequest) -> BridgeOrderResponse:
        return executor.execute_market_order(payload)

    @app.post("/positions/{ticket}/close", response_model=BridgeOrderResponse)
    def close_position(ticket: int, payload: ClosePositionRequest) -> BridgeOrderResponse:
        return executor.close_position(ticket, payload)

    return app


def start_order_server(settings: BridgeSettings, mt5_client: MT5Client) -> Thread:
    app = create_order_app(settings, mt5_client)

    def run() -> None:
        logger.info("Starting MT5 bridge order server on %s:%s", settings.mt5_bridge_host, settings.mt5_bridge_port)
        uvicorn.run(app, host=settings.mt5_bridge_host, port=settings.mt5_bridge_port, log_level=settings.log_level.lower())

    thread = Thread(target=run, name="torum-mt5-order-server", daemon=True)
    thread.start()
    return thread

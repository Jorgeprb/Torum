from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from threading import Thread
from time import perf_counter
from uuid import uuid4
from typing import Annotated, Callable

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status

from bridge.config import BridgeSettings
from bridge.mt5_client import MT5Client
from bridge.order_executor import OrderExecutor
from bridge.order_models import (
    AccountSwitchRequest,
    AccountSwitchResponse,
    BridgeOrderResponse,
    ClosePositionRequest,
    MarketOrderRequest,
    ModifyPositionTpRequest,
    OrderExecutionSettingsRequest,
    OrderExecutionSettingsResponse,
    ProfitPreviewRequest,
    ProfitPreviewResponse,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OrderServerHandle:
    server: uvicorn.Server
    thread: Thread

    def stop(self, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            logger.error("MT5 order server did not stop within %.1fs", timeout)


def create_order_app(
    settings: BridgeSettings,
    mt5_client: MT5Client,
    account_switch_handler: Callable[[int, str], tuple[object, object]] | None = None,
) -> FastAPI:
    app = FastAPI(title="Torum MT5 Bridge", version="0.5.0")
    executor = OrderExecutor(settings, mt5_client)

    @app.middleware("http")
    async def request_timing(request: Request, call_next):
        request_id = (request.headers.get("X-Request-ID") or uuid4().hex)[:128]
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception(
                "bridge_request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        log = logger.debug if request.url.path == "/health" else logger.info
        log(
            "bridge_request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        return response

    def require_bridge_token(
        token: Annotated[str | None, Header(alias="X-Torum-Service-Token")] = None,
    ) -> None:
        configured = settings.torum_service_token.get_secret_value() if settings.torum_service_token else ""
        if not configured:
            if settings.mt5_bridge_host not in {"127.0.0.1", "localhost", "::1"}:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TORUM_SERVICE_TOKEN is required when bridge is not bound to localhost",
                )
            return
        if token is None or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")

    protected = Depends(require_bridge_token)

    @app.get("/health")
    def health() -> dict[str, object]:
        connected = mt5_client.is_connected()
        account_payload = None
        try:
            account_payload = mt5_client.get_account_state().to_payload()
        except Exception:  # noqa: BLE001 - health endpoint must remain available
            account_payload = None
        return {
            "ok": True,
            "connected_to_mt5": connected,
            "order_execution_enabled": settings.mt5_allow_order_execution,
            "market_data_only": settings.mt5_market_data_only,
            "account": account_payload,
        }

    @app.get("/account", dependencies=[protected])
    def account() -> dict[str, object]:
        return mt5_client.get_account_state().to_payload()

    @app.get("/accounts/discover", dependencies=[protected])
    def discover_accounts() -> list[dict[str, object]]:
        try:
            return mt5_client.discover_terminal_accounts()
        except Exception as exc:  # noqa: BLE001 - terminal filesystem/vendor boundary
            logger.warning("MT5 account discovery failed: %s", exc)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post("/accounts/switch", response_model=AccountSwitchResponse, dependencies=[protected])
    def switch_account(payload: AccountSwitchRequest) -> AccountSwitchResponse:
        try:
            handler = account_switch_handler or mt5_client.switch_account
            previous, current = handler(payload.login, payload.server)
            # Broker-specific symbol/filling metadata must never survive an
            # account switch, even when both accounts use similar symbols.
            executor.reset_account_caches()
            previous_payload = previous.to_payload() if hasattr(previous, "to_payload") else None
            current_payload = current.to_payload() if hasattr(current, "to_payload") else None
            if not isinstance(current_payload, dict):
                raise RuntimeError("MT5 switch handler did not return an account state")
            return AccountSwitchResponse(
                previous_account=previous_payload,
                account=current_payload,
                generation=mt5_client.account_generation,
                message="MT5 account switched",
            )
        except Exception as exc:  # noqa: BLE001 - vendor/login boundary
            logger.warning("MT5 account switch failed login=%s server=%s error=%s", payload.login, payload.server, exc)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/positions", dependencies=[protected])
    def positions() -> list[dict[str, object]]:
        mt5_positions = mt5_client.get_positions()
        if mt5_positions is None:
            return []
        return [position._asdict() if hasattr(position, "_asdict") else dict(position) for position in mt5_positions]

    @app.get("/rates/{broker_symbol}", dependencies=[protected])
    def rates(
        broker_symbol: str,
        timeframe: str = Query(default="D1"),
        count: int = Query(default=120, ge=1, le=500),
        start_pos: int = Query(default=1, ge=0),
    ) -> list[dict[str, object]]:
        return mt5_client.get_rates(broker_symbol, timeframe=timeframe, count=count, start_pos=start_pos)

    @app.get("/settings/order-execution", response_model=OrderExecutionSettingsResponse, dependencies=[protected])
    def get_order_execution_settings() -> OrderExecutionSettingsResponse:
        return OrderExecutionSettingsResponse(
            enabled=settings.mt5_allow_order_execution,
            allowed_account_modes=sorted(settings.allowed_account_modes),
            enable_real_trading=settings.mt5_enable_real_trading,
            message="Runtime MT5 order execution setting",
        )

    @app.patch("/settings/order-execution", response_model=OrderExecutionSettingsResponse, dependencies=[protected])
    def patch_order_execution_settings(payload: OrderExecutionSettingsRequest) -> OrderExecutionSettingsResponse:
        settings.mt5_allow_order_execution = payload.enabled
        if payload.allowed_account_modes is not None:
            normalized_modes = sorted({mode.strip().upper() for mode in payload.allowed_account_modes if mode.strip()})
            settings.mt5_allowed_account_modes = ",".join(normalized_modes)
        if payload.enable_real_trading is not None:
            settings.mt5_enable_real_trading = payload.enable_real_trading
        logger.warning(
            "MT5 order execution runtime setting changed: enabled=%s allowed_account_modes=%s enable_real_trading=%s",
            settings.mt5_allow_order_execution,
            sorted(settings.allowed_account_modes),
            settings.mt5_enable_real_trading,
        )
        return OrderExecutionSettingsResponse(
            enabled=settings.mt5_allow_order_execution,
            allowed_account_modes=sorted(settings.allowed_account_modes),
            enable_real_trading=settings.mt5_enable_real_trading,
            message="MT5 order execution updated at runtime",
        )

    @app.post("/orders/market", response_model=BridgeOrderResponse, dependencies=[protected])
    def market_order(payload: MarketOrderRequest) -> BridgeOrderResponse:
        return executor.execute_market_order(payload)

    @app.post("/positions/{ticket}/close", response_model=BridgeOrderResponse, dependencies=[protected])
    def close_position(ticket: int, payload: ClosePositionRequest) -> BridgeOrderResponse:
        return executor.close_position(ticket, payload)

    @app.get("/positions/{ticket}/close-deal", dependencies=[protected])
    def close_deal(
        ticket: int,
        deal: int | None = Query(default=None),
        expected_account_login: int | None = Query(default=None),
        expected_account_server: str | None = Query(default=None),
    ) -> dict[str, object]:
        return executor.close_deal(
            ticket,
            deal,
            expected_account_login=expected_account_login,
            expected_account_server=expected_account_server,
        )

    @app.patch("/positions/{ticket}/tp", response_model=BridgeOrderResponse, dependencies=[protected])
    def modify_position_tp(ticket: int, payload: ModifyPositionTpRequest) -> BridgeOrderResponse:
        return executor.modify_position_tp(ticket, payload)

    @app.post("/profit-preview", response_model=ProfitPreviewResponse, dependencies=[protected])
    def profit_preview(payload: ProfitPreviewRequest) -> ProfitPreviewResponse:
        return executor.calculate_profit(payload)

    return app


def start_order_server(
    settings: BridgeSettings,
    mt5_client: MT5Client,
    account_switch_handler: Callable[[int, str], tuple[object, object]] | None = None,
) -> OrderServerHandle:
    app = create_order_app(settings, mt5_client, account_switch_handler=account_switch_handler)
    config = uvicorn.Config(
        app,
        host=settings.mt5_bridge_host,
        port=settings.mt5_bridge_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)

    def run() -> None:
        logger.info("Starting MT5 bridge order server on %s:%s", settings.mt5_bridge_host, settings.mt5_bridge_port)
        server.run()

    thread = Thread(target=run, name="torum-mt5-order-server", daemon=False)
    thread.start()
    return OrderServerHandle(server=server, thread=thread)

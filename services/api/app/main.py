from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.auth.router import router as auth_router
from app.alerts.routes import router as alerts_router
from app.admin.system import router as admin_system_router
from app.candles.router import router as candles_router
from app.chart.routes import router as chart_router
from app.core.config import get_settings
from app.indicators.routes import router as indicators_router
from app.indicators.service import seed_default_indicators
from app.drawings.routes import router as drawings_router
from app.core.logging import configure_logging
from app.core.request_context import new_request_id, reset_request_id, set_request_id
from app.market_data.mock import MockMarketService
from app.market_data.diagnostics_router import router as market_diagnostics_router
from app.market_data.router import router as mock_market_router
from app.market_context.routes import router as market_context_router
from app.market_context.scheduler import dollar_strength_scheduler
from app.mt5.router import router as mt5_router
from app.news.routes import router as news_router
from app.news.scheduler import news_provider_scheduler
from app.news.service import seed_global_news_settings
from app.no_trade_zones.routes import router as no_trade_zones_router
from app.orders.router import router as orders_router
from app.positions.router import router as positions_router
from app.risk.router import router as risk_router
from app.settings.router import router as settings_router
from app.settings.trading_service import seed_global_trading_settings
from app.strategies.routes import router as strategies_router
from app.strategies.service import seed_strategy_engine_defaults
from app.symbols.router import router as symbols_router
from app.symbols.service import seed_default_symbols
from app.ticks.router import router as ticks_router
from app.trade_history.routes import router as trade_history_router
from app.trade_jobs.service import trade_job_worker
from app.trading.routes import router as trading_router
from app.users.service import seed_initial_users
from app.websockets.manager import market_ws_manager
from app.websockets.router import router as websocket_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.mock_market = MockMarketService()
    seed_initial_users()
    seed_default_symbols()
    seed_global_trading_settings()
    seed_global_news_settings()
    seed_default_indicators()
    seed_strategy_engine_defaults()
    settings = get_settings()
    worker_count = max(
        int(os.getenv("WEB_CONCURRENCY", "1") or "1"),
        int(os.getenv("UVICORN_WORKERS", "1") or "1"),
    )
    if settings.enforce_single_worker and worker_count > 1:
        raise RuntimeError(
            "Torum API single-worker mode is enabled to guarantee one internal scheduler/job worker; disable only when schedulers are externalized"
        )
    market_ws_manager.start()
    trade_job_worker.start()
    if settings.run_internal_schedulers:
        news_provider_scheduler.start()
        dollar_strength_scheduler.start()
    else:
        logger.warning("Internal schedulers disabled; ensure exactly one external scheduler instance is running")
    logger.info("Torum API started")
    try:
        yield
    finally:
        if settings.run_internal_schedulers:
            dollar_strength_scheduler.stop()
            news_provider_scheduler.stop()
        trade_job_worker.stop()
        market_ws_manager.stop()
        await app.state.mock_market.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.project_name} API",
        version="0.1.0",
        lifespan=lifespan,
    )
    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = new_request_id(request.headers.get("X-Request-ID"))
        token = set_request_id(request_id)
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception(
                "http_request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = request_id
        elapsed_ms = (perf_counter() - started) * 1000
        log = logger.debug if request.url.path in {"/health", "/api/health"} else logger.info
        log(
            "http_request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Historical simulation payloads can contain thousands of candles and
    # debug events. Compress them without changing the API contract.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(settings_router, prefix=settings.api_v1_prefix)
    app.include_router(symbols_router, prefix="/api")
    app.include_router(ticks_router, prefix="/api")
    app.include_router(candles_router, prefix="/api")
    app.include_router(mock_market_router, prefix="/api")
    app.include_router(market_diagnostics_router, prefix="/api")
    app.include_router(market_context_router, prefix="/api")
    app.include_router(mt5_router, prefix="/api")
    app.include_router(news_router, prefix="/api")
    app.include_router(no_trade_zones_router, prefix="/api")
    app.include_router(indicators_router, prefix="/api")
    app.include_router(drawings_router, prefix="/api")
    app.include_router(chart_router, prefix="/api")
    app.include_router(strategies_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    app.include_router(admin_system_router, prefix="/api")
    app.include_router(risk_router, prefix="/api")
    app.include_router(trading_router, prefix="/api")
    app.include_router(orders_router, prefix="/api")
    app.include_router(positions_router, prefix="/api")
    app.include_router(trade_history_router, prefix="/api")
    app.include_router(websocket_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "torum-api"}

    @app.get("/api/health", tags=["health"])
    def api_health() -> dict[str, str]:
        return health()

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {"name": settings.project_name, "status": "running"}

    return app


app = create_app()

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.candles.router import router as candles_router
from app.chart.routes import router as chart_router
from app.core.config import get_settings
from app.indicators.routes import router as indicators_router
from app.indicators.service import seed_default_indicators
from app.drawings.routes import router as drawings_router
from app.core.logging import configure_logging
from app.market_data.mock import MockMarketService
from app.market_data.router import router as mock_market_router
from app.mt5.router import router as mt5_router
from app.news.routes import router as news_router
from app.news.service import seed_global_news_settings
from app.no_trade_zones.routes import router as no_trade_zones_router
from app.orders.router import router as orders_router
from app.positions.router import router as positions_router
from app.settings.router import router as settings_router
from app.settings.trading_service import seed_global_trading_settings
from app.strategies.routes import router as strategies_router
from app.strategies.service import seed_strategy_engine_defaults
from app.symbols.router import router as symbols_router
from app.symbols.service import seed_default_symbols
from app.ticks.router import router as ticks_router
from app.trading.routes import router as trading_router
from app.users.service import seed_initial_users
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
    logger.info("Torum API started")
    try:
        yield
    finally:
        await app.state.mock_market.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.project_name} API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(settings_router, prefix=settings.api_v1_prefix)
    app.include_router(symbols_router, prefix="/api")
    app.include_router(ticks_router, prefix="/api")
    app.include_router(candles_router, prefix="/api")
    app.include_router(mock_market_router, prefix="/api")
    app.include_router(mt5_router, prefix="/api")
    app.include_router(news_router, prefix="/api")
    app.include_router(no_trade_zones_router, prefix="/api")
    app.include_router(indicators_router, prefix="/api")
    app.include_router(drawings_router, prefix="/api")
    app.include_router(chart_router, prefix="/api")
    app.include_router(strategies_router, prefix="/api")
    app.include_router(trading_router, prefix="/api")
    app.include_router(orders_router, prefix="/api")
    app.include_router(positions_router, prefix="/api")
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

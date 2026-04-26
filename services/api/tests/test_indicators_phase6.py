from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.indicators.engine import IndicatorEngine
from app.indicators.models import IndicatorConfig
from app.indicators.plugins.custom_zone_example import CustomZoneExamplePlugin
from app.indicators.registry import indicator_registry
from app.indicators.routes import router as indicators_router
from app.indicators.service import IndicatorService
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.symbols.service import DEFAULT_SYMBOL_MAPPINGS
from app.candles.models import Candle
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = testing_session()
    db.add(
        SymbolMapping(
            internal_symbol="DXY",
            broker_symbol="DXY",
            display_name="US Dollar Index",
            enabled=True,
            asset_class="INDEX",
            tradable=False,
            analysis_only=True,
            digits=2,
            point=0.01,
            contract_size=1.0,
        )
    )
    db.add(
        TradingSettings(
            user_id=None,
            trading_mode="PAPER",
            live_trading_enabled=False,
            require_live_confirmation=True,
            default_volume=0.01,
            default_magic_number=260426,
            default_deviation_points=20,
            allow_market_orders=True,
            allow_pending_orders=False,
        )
    )
    # SQLite returns naive datetimes for DateTime(timezone=True), and bulk
    # RETURNING cannot match timezone-aware composite PK values reliably.
    start = datetime(2026, 1, 1)
    for index in range(35):
        close = 100.0 + index
        candle_time = start + timedelta(days=index)
        db.add(
            Candle(
                time=candle_time,
                internal_symbol="DXY",
                timeframe="D1",
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=0.0,
                tick_count=10,
                source="TEST",
            )
        )
    db.add(
        Tick(
            id=1,
            time=datetime.now(UTC),
            internal_symbol="DXY",
            broker_symbol="DXY",
            bid=104.0,
            ask=104.1,
            last=None,
            volume=0.0,
            source="TEST",
        )
    )
    db.commit()
    return db


def test_sma30_calculates_after_30_closes() -> None:
    db = _session()
    result = IndicatorEngine(db).calculate("SMA", "DXY", "D1", {"period": 30}, limit=35)
    points = result["output"]["points"]  # type: ignore[index]

    assert len(points) == 6
    assert points[0]["value"] == sum(100 + value for value in range(30)) / 30


def test_sma30_returns_no_points_with_less_than_period() -> None:
    db = _session()
    result = IndicatorEngine(db).calculate("SMA", "DXY", "D1", {"period": 30}, limit=20)

    assert result["output"]["points"] == []  # type: ignore[index]


def test_indicator_registry_finds_sma_and_custom_zone_shape() -> None:
    sma = indicator_registry.get("SMA")
    zone_output = CustomZoneExamplePlugin().calculate([], {}, SimpleNamespace(symbol="XAUUSD", timeframe="H1", config_id=None))

    assert sma.key == "SMA"
    assert zone_output["type"] == "zone"
    assert zone_output["zones"] == []


def test_calculate_endpoint_returns_line_output() -> None:
    db = _session()
    app = FastAPI()
    app.include_router(indicators_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).get("/api/indicators/calculate?symbol=DXY&timeframe=D1&indicator=SMA&period=30&limit=35")

    assert response.status_code == 200
    payload = response.json()
    assert payload["output"]["type"] == "line"
    assert payload["output"]["name"] == "SMA30"
    assert len(payload["output"]["points"]) == 6


def test_dxy_seed_mapping_is_enabled_analysis_only() -> None:
    dxy = next(mapping for mapping in DEFAULT_SYMBOL_MAPPINGS if mapping["internal_symbol"] == "DXY")

    assert dxy["enabled"] is True
    assert dxy["tradable"] is False
    assert dxy["analysis_only"] is True


def test_risk_manager_blocks_dxy_order_when_analysis_only() -> None:
    db = _session()
    trading_settings = db.query(TradingSettings).one()
    symbol_mapping = db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "DXY").one()

    decision = RiskManager(db).evaluate(
        order=ManualOrderRequest(internal_symbol="DXY", side="BUY", volume=0.01),
        trading_settings=trading_settings,
        symbol_mapping=symbol_mapping,
        mt5_status=SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN"),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "analysis-only" in "; ".join(decision.reasons)


def test_chart_overlays_includes_sma_when_configured() -> None:
    db = _session()
    indicators = IndicatorService(db).register_defaults()
    sma = next(indicator for indicator in indicators if indicator.plugin_key == "SMA")
    config = db.query(IndicatorConfig).filter(IndicatorConfig.indicator_id == sma.id).one()

    overlays = IndicatorService(db).calculate_active_overlays("DXY", "D1")

    assert config.enabled is True
    assert overlays[0]["type"] == "line"
    assert overlays[0]["name"] == "SMA30"

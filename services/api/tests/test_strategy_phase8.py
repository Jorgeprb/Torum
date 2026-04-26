from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.db.base import Base
from app.drawings.models import ChartDrawing
from app.news.service import get_global_news_settings
from app.orders.models import Order
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.strategies.models import StrategyConfig, StrategyRun, StrategySignal
from app.strategies.plugins.example_manual_zone_strategy import ExampleManualZoneStrategy
from app.strategies.plugins.example_sma_dxy_filter import ExampleSmaDxyFilter
from app.strategies.registry import strategy_registry
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner
from app.strategies.service import StrategyCatalogService
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest
from app.users.models import User, UserRole


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = testing_session()
    db.add(User(id=1, username="admin", email="admin@example.com", hashed_password="test", role=UserRole.admin, is_active=True))
    db.add(
        SymbolMapping(
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSDm",
            display_name="Gold / USD",
            enabled=True,
            asset_class="METAL",
            tradable=True,
            analysis_only=False,
            digits=2,
            point=0.01,
            contract_size=100.0,
        )
    )
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
            max_order_volume=1.0,
            allow_market_orders=True,
            allow_pending_orders=False,
        )
    )
    now = datetime.now(UTC)
    db.add(Tick(id=1, time=now, internal_symbol="XAUUSD", broker_symbol="XAUUSDm", bid=2325.0, ask=2325.2, last=None, volume=0.0, source="TEST"))
    start = datetime(2026, 1, 1)
    for index in range(35):
        close = 100.0 + index
        db.add(Candle(time=start + timedelta(days=index), internal_symbol="DXY", timeframe="D1", open=close, high=close + 1, low=close - 1, close=close, volume=0.0, tick_count=1, source="TEST"))
    for index in range(5):
        close = 2325.0 + index
        db.add(Candle(time=start + timedelta(hours=index), internal_symbol="XAUUSD", timeframe="H1", open=close, high=close + 1, low=close - 1, close=close, volume=0.0, tick_count=1, source="TEST"))
    db.commit()
    StrategyCatalogService(db).register_defaults()
    get_global_news_settings(db)
    return db


def _user(db: Session) -> User:
    user = db.get(User, 1)
    assert user is not None
    return user


def test_registry_registers_example_strategies() -> None:
    assert strategy_registry.get("example_sma_dxy_filter").key == "example_sma_dxy_filter"
    assert strategy_registry.get("example_manual_zone_strategy").key == "example_manual_zone_strategy"


def test_example_sma_dxy_filter_returns_none_with_metadata() -> None:
    db = _session()
    config = StrategyConfig(user_id=1, strategy_key="example_sma_dxy_filter", internal_symbol="XAUUSD", timeframe="H1", enabled=True, mode="PAPER", params_json={})
    db.add(config)
    db.commit()
    from app.strategies.engine import StrategyContextBuilder

    signal = ExampleSmaDxyFilter().generate_signal(StrategyContextBuilder(db).build(config))

    assert signal.signal_type == "NONE"
    assert signal.metadata["dollar_strength"] == "STRONG"


def test_strategy_config_disabled_does_not_run() -> None:
    db = _session()
    settings = get_global_strategy_settings(db)
    settings.strategies_enabled = True
    config = StrategyConfig(user_id=1, strategy_key="example_sma_dxy_filter", internal_symbol="XAUUSD", timeframe="H1", enabled=False, mode="PAPER", params_json={})
    db.add(config)
    db.commit()

    result = StrategyRunner(db).run_config(config, _user(db))

    assert result.ok is False
    assert "disabled" in result.message.lower()


def test_strategies_enabled_false_blocks_run() -> None:
    db = _session()
    config = StrategyConfig(user_id=1, strategy_key="example_sma_dxy_filter", internal_symbol="XAUUSD", timeframe="H1", enabled=True, mode="PAPER", params_json={})
    db.add(config)
    db.commit()

    result = StrategyRunner(db).run_config(config, _user(db))

    assert result.ok is False
    assert "Strategies are disabled" in result.message


def test_signal_and_run_are_saved_for_none_signal() -> None:
    db = _session()
    settings = get_global_strategy_settings(db)
    settings.strategies_enabled = True
    config = StrategyConfig(user_id=1, strategy_key="example_sma_dxy_filter", internal_symbol="XAUUSD", timeframe="H1", enabled=True, mode="PAPER", params_json={})
    db.add(config)
    db.commit()

    result = StrategyRunner(db).run_config(config, _user(db))

    assert result.ok is True
    assert db.query(StrategyRun).count() == 1
    assert db.query(StrategySignal).count() == 1
    assert db.query(StrategySignal).one().status == "IGNORED"


def test_risk_manager_blocks_live_when_strategy_live_disabled() -> None:
    db = _session()
    strategy_settings = get_global_strategy_settings(db)
    strategy_settings.strategies_enabled = True
    order = ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01)
    trading_settings = SimpleNamespace(
        trading_mode="LIVE",
        live_trading_enabled=True,
        require_live_confirmation=False,
        max_order_volume=1.0,
        allow_market_orders=True,
        is_paused=False,
    )
    mt5_status = SimpleNamespace(connected_to_mt5=True, account_trade_mode="REAL", updated_at=datetime.now(UTC))

    decision = RiskManager(db).evaluate_strategy_order(
        order=order,
        trading_settings=trading_settings,
        strategy_settings=strategy_settings,
        symbol_mapping=db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one(),
        mt5_status=mt5_status,
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "Strategy LIVE execution is disabled" in decision.reasons


def test_example_manual_zone_strategy_reads_visible_manual_zone() -> None:
    db = _session()
    db.add(
        ChartDrawing(
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="H1",
            drawing_type="manual_zone",
            payload_json={"time1": 1777209600, "time2": None, "price_min": 2320.0, "price_max": 2330.0, "direction": "BUY"},
            style_json={},
            metadata_json={},
            visible=True,
            locked=False,
            source="MANUAL",
        )
    )
    config = StrategyConfig(
        user_id=1,
        strategy_key="example_manual_zone_strategy",
        internal_symbol="XAUUSD",
        timeframe="H1",
        enabled=True,
        mode="PAPER",
        params_json={"dry_run": True, "volume": 0.01},
    )
    db.add(config)
    db.commit()
    from app.strategies.engine import StrategyContextBuilder

    signal = ExampleManualZoneStrategy().generate_signal(StrategyContextBuilder(db).build(config))

    assert signal.signal_type == "NONE"
    assert signal.metadata["manual_zone_id"]


def test_manual_zone_strategy_can_create_strategy_paper_order_when_not_dry_run() -> None:
    db = _session()
    settings = get_global_strategy_settings(db)
    settings.strategies_enabled = True
    db.add(
        ChartDrawing(
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="H1",
            drawing_type="manual_zone",
            payload_json={"time1": 1777209600, "time2": None, "price_min": 2320.0, "price_max": 2330.0, "direction": "BUY"},
            style_json={},
            metadata_json={},
            visible=True,
            locked=False,
            source="MANUAL",
        )
    )
    config = StrategyConfig(
        user_id=1,
        strategy_key="example_manual_zone_strategy",
        internal_symbol="XAUUSD",
        timeframe="H1",
        enabled=True,
        mode="PAPER",
        params_json={"dry_run": False, "volume": 0.01},
    )
    db.add(config)
    db.commit()

    result = StrategyRunner(db).run_config(config, _user(db))

    assert result.ok is True
    assert db.query(Order).one().source == "STRATEGY"
    assert db.query(Order).one().strategy_key == "example_manual_zone_strategy"
    assert db.query(StrategySignal).one().status == "ORDER_EXECUTED"

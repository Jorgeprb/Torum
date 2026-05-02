from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.db.base import Base
from app.news.models import NewsEvent, NewsSettings  # noqa: F401
from app.news.service import get_global_news_settings
from app.no_trade_zones.models import NoTradeZone
from app.orders.models import Order  # noqa: F401
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner
from app.strategies.torum_v1 import (
    TorumV1OperationZone,
    TorumV1StatusService,
    detect_pullbacks,
    is_bullish_confirmation,
    is_candle_inside_operation_zone,
    operation_zones_from_drawings,
    should_buy_torum_v1,
)
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest
from app.users.models import User, UserRole

MADRID = ZoneInfo("Europe/Madrid")


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
    for index, symbol in enumerate(("XAUEUR", "XAUUSD"), start=1):
        db.add(
            SymbolMapping(
                internal_symbol=symbol,
                broker_symbol=symbol,
                display_name=symbol,
                enabled=True,
                asset_class="METAL",
                tradable=True,
                analysis_only=False,
                digits=2,
                point=0.01,
                contract_size=100.0,
            )
        )
        db.add(Tick(id=index, time=datetime.now(UTC), internal_symbol=symbol, broker_symbol=symbol, bid=2300.0, ask=2300.2, volume=0.0, source="TEST"))
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
    settings = get_global_strategy_settings(db)
    settings.strategies_enabled = True
    get_global_news_settings(db)
    db.commit()
    return db


def _madrid(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, day, hour, minute, tzinfo=MADRID)


def _config(db: Session, symbol: str, timeframe: str = "H2") -> StrategyConfig:
    config = StrategyConfig(
        user_id=1,
        strategy_key="torum_v1",
        internal_symbol=symbol,
        timeframe=timeframe,
        enabled=True,
        mode="PAPER",
        params_json={
            "enabled": True,
            "use_news": True,
            "timeframe": timeframe,
            "session_start": "09:00" if symbol == "XAUEUR" else "15:30",
            "session_end": "15:00" if symbol == "XAUEUR" else "21:00",
        },
    )
    db.add(config)
    db.commit()
    return config


def _h1(db: Session, symbol: str, start_local: datetime, open_: float, close: float, low: float | None = None) -> None:
    db.add(
        Candle(
            time=start_local.astimezone(UTC).replace(tzinfo=None),
            internal_symbol=symbol,
            timeframe="H1",
            open=open_,
            high=max(open_, close) + 1,
            low=min(open_, close) - 1 if low is None else low,
            close=close,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )


def _m5_candle(start_local: datetime, open_: float, high: float, low: float, close: float) -> SimpleNamespace:
    return SimpleNamespace(
        time=start_local.astimezone(UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def _m5(
    db: Session,
    symbol: str,
    start_local: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> None:
    db.add(
        Candle(
            time=start_local.astimezone(UTC).replace(tzinfo=None),
            internal_symbol=symbol,
            timeframe="M5",
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )


def _two_hour_window(
    db: Session,
    symbol: str,
    start_local: datetime,
    *,
    open_: float,
    close: float,
    low: float,
    previous_low: float,
) -> None:
    _h1(db, symbol, start_local - timedelta(hours=2), 90, 91, previous_low)
    _h1(db, symbol, start_local - timedelta(hours=1), 91, 92, previous_low + 1)
    _h1(db, symbol, start_local, open_, (open_ + close) / 2, low)
    _h1(db, symbol, start_local + timedelta(hours=1), (open_ + close) / 2, close, low + 1)
    db.commit()


def test_xaueur_2h_bullish_unlocks() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "bullish_closed_candle"


def test_xaueur_2h_bearish_holds_previous_low_unlocks() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=98, low=95, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "held_previous_low"


def test_xaueur_2h_bearish_breaks_previous_low_stays_locked() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=98, low=80, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "broke_previous_low"


def test_xaueur_after_15_locked() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 15, 0)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "outside_session"


def test_xauusd_before_17_locked() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _two_hour_window(db, "XAUUSD", _madrid(1, 15), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 16, 30)).assets["XAUUSD"]

    assert status.status == "LOCKED"


def test_xauusd_15_17_bullish_unlocks() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _two_hour_window(db, "XAUUSD", _madrid(1, 15), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 17, 5)).assets["XAUUSD"]

    assert status.status == "UNLOCKED"


def test_xauusd_after_21_locked() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _two_hour_window(db, "XAUUSD", _madrid(1, 15), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 21, 0)).assets["XAUUSD"]

    assert status.status == "LOCKED"
    assert status.reason == "outside_session"


def test_news_active_blocks_bot_but_manual_can_open() -> None:
    db = _session()
    settings = get_global_news_settings(db)
    settings.block_trading_during_news = True
    now = datetime.now(UTC)
    db.add(
        NoTradeZone(
            source="TEST",
            reason="HIGH USD",
            internal_symbol="XAUUSD",
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(minutes=10),
            enabled=True,
            blocks_trading=True,
            visual_only=False,
        )
    )
    db.commit()
    trading_settings = db.query(TradingSettings).one()
    symbol_mapping = db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one()
    order = ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01)
    mt5_status = SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN")

    manual = RiskManager(db).evaluate(order, trading_settings, symbol_mapping, mt5_status, 120)
    bot = RiskManager(db).evaluate_strategy_order(order, trading_settings, get_global_strategy_settings(db), symbol_mapping, mt5_status, 120, user_id=1)

    assert manual.allowed is True
    assert bot.allowed is False
    assert "noticia" in "; ".join(bot.reasons).lower()


def test_daily_reset_yesterday_unlock_does_not_unlock_today() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(2, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"


def test_pullback_019_not_detected() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.81, 99.9),
    ]

    assert detect_pullbacks(candles, threshold=0.20, lookback=12) == []


def test_pullback_021_detected() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.79, 99.9),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20, lookback=12)

    assert len(pullbacks) == 1
    assert pullbacks[0].pullback_pct > 0.20


def test_pullback_detected_next_bearish_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.85, 99.6, 99.7),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99, 101)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_threshold_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "waiting_bullish_confirmation"


def test_pullback_detected_bullish_outside_zone_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 90, 95)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_threshold_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "confirmation_outside_operation_zone"


def test_pullback_detected_bullish_inside_zone_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99, 101)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_threshold_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is True
    assert decision.zone is zone


def test_rectangle_not_activated_does_not_count() -> None:
    drawing = ChartDrawing(
        id="zone-1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        drawing_type="rectangle",
        name=None,
        payload_json={"time1": int(_madrid(1, 9).timestamp()), "time2": int(_madrid(1, 10).timestamp()), "price1": 99, "price2": 101},
        style_json={},
        metadata_json={},
        locked=False,
        visible=True,
        source="MANUAL",
    )

    assert operation_zones_from_drawings([drawing]) == []


def test_active_zone_time_price_outside_no_buy() -> None:
    candle = _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9)
    price_zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 80, 90)
    time_zone = TorumV1OperationZone("z2", "rectangle", int(_madrid(1, 11).timestamp()), int(_madrid(1, 12).timestamp()), 99, 101)

    assert is_bullish_confirmation(candle) is True
    assert is_candle_inside_operation_zone(candle, price_zone) is False
    assert is_candle_inside_operation_zone(candle, time_zone) is False


def test_duplicate_same_signal_candle_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99, 101)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"last_signal_candle_time": int(_madrid(1, 9, 10).timestamp())},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "duplicate_signal_candle"


def test_locked_asset_rejects_strategy_order_no_manual_block() -> None:
    db = _session()
    config = _config(db, "XAUUSD", "H2")
    config.params_json = {
        **config.params_json,
        "enable_operation_zones": True,
        "require_zone": True,
        "pullback_threshold_pct": 0.2,
        "pullback_lookback_bars": 12,
    }
    db.add(
        ChartDrawing(
            user_id=1,
            internal_symbol="XAUUSD",
            timeframe="M5",
            drawing_type="rectangle",
            name=None,
            payload_json={"time1": int(_madrid(1, 9).timestamp()), "time2": int(_madrid(1, 10).timestamp()), "price1": 99, "price2": 101},
            style_json={},
            metadata_json={"torum_v1_zone_enabled": True, "zone_type": "OPERATION_ZONE", "direction": "BUY"},
            locked=False,
            visible=True,
            source="MANUAL",
        )
    )
    _m5(db, "XAUUSD", _madrid(1, 9), 100, 100, 99.9, 99.95)
    _m5(db, "XAUUSD", _madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8)
    _m5(db, "XAUUSD", _madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9)
    db.commit()

    result = StrategyRunner(db).run_config(config, db.get(User, 1))
    manual = RiskManager(db).evaluate(
        ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01),
        db.query(TradingSettings).one(),
        db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one(),
        SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN"),
        120,
    )

    assert result.ok is False
    assert result.order_id is None
    assert manual.allowed is True

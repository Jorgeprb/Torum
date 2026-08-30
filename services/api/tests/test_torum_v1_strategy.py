from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import PushSubscription
from app.candles.models import Candle
from app.drawings.models import ChartDrawing
from app.db.base import Base
from app.news.models import NewsEvent, NewsSettings  # noqa: F401
from app.news.service import get_global_news_settings
from app.no_trade_zones.models import NoTradeZone
from app.orders.models import Order  # noqa: F401
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.strategies.ath import ath_price_zones, get_or_update_symbol_ath, set_symbol_ath_level
from app.strategies.models import StrategyConfig, StrategySignal
from app.strategies.notifications import send_torum_v1_unlock_notifications
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner, _record_torum_v1_executed_entry_cycle, _release_torum_v1_signal_attempt, _torum_v1_desired_multiplier_for_ath_zone
from app.strategies.schemas import StrategyConfigCreate, StrategyConfigUpdate
from app.strategies.service import StrategyCatalogService
from app.strategies.torum_v1_config import TorumV1Params
from app.market_context.models import DollarStrengthSnapshot
from app.strategies.torum_v1 import (
    TorumV1OperationZone,
    TorumV1SupportZone,
    TorumV1StatusService,
    detect_pullbacks,
    desired_multiplier_for_support,
    is_bullish_confirmation,
    is_candle_inside_operation_zone,
    is_pullback_low_inside_operation_zone,
    operation_zones_from_drawings,
    pullback_debug_payload,
    should_buy_torum_v1,
)
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest
from app.users.models import User, UserRole

MADRID = ZoneInfo("Europe/Madrid")
BROKER = ZoneInfo("Etc/GMT-3")


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
            time=_broker_chart_time(start_local),
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


def _tf_candle(
    db: Session,
    symbol: str,
    timeframe: str,
    start_local: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> None:
    db.add(
        Candle(
            time=_broker_chart_time(start_local),
            internal_symbol=symbol,
            timeframe=timeframe,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )


def _broker_chart_time(start_local: datetime) -> datetime:
    return start_local.astimezone(BROKER).replace(tzinfo=None)


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
    previous_bearish: bool = False,
) -> None:
    previous_open = 92 if previous_bearish else 90
    previous_mid = 91
    previous_close = 90 if previous_bearish else 92
    _h1(db, symbol, start_local - timedelta(hours=2), previous_open, previous_mid, previous_low)
    _h1(db, symbol, start_local - timedelta(hours=1), previous_mid, previous_close, previous_low + 1)
    _h1(db, symbol, start_local, open_, (open_ + close) / 2, low)
    _h1(db, symbol, start_local + timedelta(hours=1), (open_ + close) / 2, close, low + 1)
    db.commit()


def test_manual_ath_overrides_imported_candle_high() -> None:
    db = _session()
    db.add(
        Candle(
            time=datetime(2026, 5, 1, tzinfo=UTC),
            internal_symbol="XAUUSD",
            timeframe="H1",
            open=2000,
            high=2200,
            low=1990,
            close=2100,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )
    db.commit()

    set_symbol_ath_level(db, "XAUUSD", "manual", 2500)
    db.add(
        Candle(
            time=datetime(2026, 5, 2, tzinfo=UTC),
            internal_symbol="XAUUSD",
            timeframe="H1",
            open=2600,
            high=3000,
            low=2500,
            close=2700,
            volume=0.0,
            tick_count=1,
            source="TEST",
        )
    )
    db.commit()

    assert get_or_update_symbol_ath(db, "XAUUSD") == 2500
    assert ath_price_zones(db, "XAUUSD")[0]["ath_price"] == 2500

    set_symbol_ath_level(db, "XAUUSD", "auto")

    assert get_or_update_symbol_ath(db, "XAUUSD") == 3000


def _three_hour_window(
    db: Session,
    symbol: str,
    start_local: datetime,
    *,
    open_: float,
    close: float,
    low: float,
    previous_low: float,
    previous_bearish: bool = False,
) -> None:
    previous_values = (96, 94, 92, 90) if previous_bearish else (90, 92, 94, 96)
    for index, offset in enumerate(range(3, 0, -1)):
        _h1(db, symbol, start_local - timedelta(hours=offset), previous_values[index], previous_values[index + 1], previous_low + index)
    _h1(db, symbol, start_local, open_, (open_ * 2 + close) / 3, low)
    _h1(db, symbol, start_local + timedelta(hours=1), (open_ * 2 + close) / 3, (open_ + close * 2) / 3, low + 1)
    _h1(db, symbol, start_local + timedelta(hours=2), (open_ + close * 2) / 3, close, low + 2)
    db.commit()


def test_xaueur_2h_bullish_unlocks() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "bullish_closed_candle"


def test_manual_unlock_bypasses_only_h2_h3_requirement_for_current_session_day() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.params_json = {
        **config.params_json,
        "manual_unlock_override": "UNLOCKED",
        "manual_unlock_override_day": "2026-05-01",
    }
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "manual_unlock"
    assert status.manual_override == "UNLOCKED"


def test_manual_lock_overrides_an_automatic_bullish_unlock_for_current_session_day() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.params_json = {
        **config.params_json,
        "manual_unlock_override": "LOCKED",
        "manual_unlock_override_day": "2026-05-01",
    }
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "manual_lock"
    assert status.manual_override == "LOCKED"


def test_manual_unlock_does_not_bypass_session_hours() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.params_json = {
        **config.params_json,
        "manual_unlock_override": "UNLOCKED",
        "manual_unlock_override_day": "2026-05-01",
    }
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 15, 0)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "outside_session"
    assert status.manual_override == "UNLOCKED"


def test_manual_unlock_expires_automatically_on_the_next_madrid_day() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.params_json = {
        **config.params_json,
        "manual_unlock_override": "UNLOCKED",
        "manual_unlock_override_day": "2026-05-01",
    }
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(2, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.manual_override is None




def test_xaueur_2h_doji_unlocks_even_with_min_body_filter() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.params_json = {**config.params_json, "unlock_min_body_pct": 0.25}
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=100, low=99, previous_low=90)
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "doji_closed_candle"


def test_xaueur_visual_status_unlocks_even_when_strategy_off() -> None:
    db = _session()
    config = _config(db, "XAUEUR", "H2")
    config.enabled = False
    config.params_json = {**config.params_json, "enabled": False, "timeframe": "H3"}
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.enabled is False
    assert status.timeframe == "H2/H3"
    assert status.status == "UNLOCKED"
    assert status.reason == "bullish_closed_candle"


def test_xaueur_visual_status_unlocks_without_config() -> None:
    db = _session()
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.enabled is False
    assert status.status == "UNLOCKED"


def test_xaueur_2h_bearish_holds_previous_low_unlocks() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=98, low=95, previous_low=90, previous_bearish=True)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "UNLOCKED"
    assert status.reason == "held_previous_low"


def test_xaueur_2h_bearish_holds_previous_low_but_previous_bullish_stays_locked() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=98, low=95, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "waiting_closed_candle"


def test_xaueur_2h_bearish_breaks_previous_low_stays_locked() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=98, low=80, previous_low=90, previous_bearish=True)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"
    assert status.reason == "waiting_closed_candle"


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


def test_xauusd_h2_fails_then_h3_bullish_unlocks() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 13), 110, 111, 90, 100)
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 15), 100, 101, 80, 95)
    _tf_candle(db, "XAUUSD", "H3", _madrid(1, 15), 95, 106, 80, 105)
    db.commit()

    waiting = TorumV1StatusService(db).status_for_user(1, _madrid(1, 17, 30)).assets["XAUUSD"]
    unlocked = TorumV1StatusService(db).status_for_user(1, _madrid(1, 18, 5)).assets["XAUUSD"]

    assert waiting.status == "LOCKED"
    assert waiting.reason == "waiting_closed_candle"
    assert unlocked.status == "UNLOCKED"
    assert unlocked.reason == "bullish_closed_candle"




def test_xauusd_h3_doji_unlocks_when_h2_did_not() -> None:
    db = _session()
    config = _config(db, "XAUUSD", "H2")
    config.params_json = {**config.params_json, "unlock_min_body_pct": 0.25}
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 13), 110, 111, 90, 100)
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 15), 100, 101, 80, 95)
    _tf_candle(db, "XAUUSD", "H3", _madrid(1, 15), 100, 101, 80, 100)
    db.commit()

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 18, 5)).assets["XAUUSD"]

    assert status.status == "UNLOCKED"
    assert status.reason == "doji_closed_candle"


def test_xauusd_h2_and_h3_fail_then_next_h2_unlocks() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 13), 110, 111, 90, 100)
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 15), 100, 101, 80, 95)
    _tf_candle(db, "XAUUSD", "H3", _madrid(1, 15), 100, 101, 80, 95)
    _tf_candle(db, "XAUUSD", "H2", _madrid(1, 17), 95, 106, 94, 105)
    db.commit()

    waiting = TorumV1StatusService(db).status_for_user(1, _madrid(1, 18, 5)).assets["XAUUSD"]
    unlocked = TorumV1StatusService(db).status_for_user(1, _madrid(1, 19, 5)).assets["XAUUSD"]

    assert waiting.status == "LOCKED"
    assert waiting.reason == "waiting_closed_candle"
    assert unlocked.status == "UNLOCKED"
    assert unlocked.reason == "bullish_closed_candle"


def test_xauusd_2h_uses_broker_chart_time_for_spanish_window() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _two_hour_window(db, "XAUUSD", _madrid(1, 15), open_=110, close=100, low=95, previous_low=90, previous_bearish=True)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 17, 5)).assets["XAUUSD"]

    assert status.status == "UNLOCKED"
    assert status.reason == "held_previous_low"


def test_xauusd_2h_bearish_holds_previous_low_but_previous_bullish_stays_locked() -> None:
    db = _session()
    _config(db, "XAUUSD", "H2")
    _two_hour_window(db, "XAUUSD", _madrid(1, 15), open_=110, close=100, low=95, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 17, 5)).assets["XAUUSD"]

    assert status.status == "LOCKED"
    assert status.reason == "waiting_closed_candle"


def test_xauusd_3h_uses_broker_chart_time_for_spanish_window() -> None:
    db = _session()
    _config(db, "XAUUSD", "H3")
    _three_hour_window(db, "XAUUSD", _madrid(1, 15), open_=110, close=100, low=80, previous_low=90, previous_bearish=True)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 18, 5)).assets["XAUUSD"]

    assert status.status == "LOCKED"
    assert status.reason == "waiting_closed_candle"


def test_xauusd_3h_bearish_holds_previous_low_but_previous_bullish_stays_locked() -> None:
    db = _session()
    _config(db, "XAUUSD", "H3")
    _three_hour_window(db, "XAUUSD", _madrid(1, 15), open_=110, close=100, low=95, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(1, 18, 5)).assets["XAUUSD"]

    assert status.status == "LOCKED"
    assert status.reason == "waiting_closed_candle"


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



def test_manual_order_ignores_torum_asset_lock() -> None:
    db = _session()
    config = _config(db, "XAUUSD", "H2")
    # No valid H2/H3 unlock candle exists, so Torum automatic status is locked.
    status = TorumV1StatusService(db).asset_status("XAUUSD", config, True, _madrid(1, 18, 0))
    assert status.status == "LOCKED"

    trading_settings = db.query(TradingSettings).one()
    symbol_mapping = db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one()
    order = ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01)
    mt5_status = SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN")

    # Manual execution deliberately does not call evaluate_strategy_order(), so
    # H2/H3/manual-lock state cannot veto a user's BUY.
    manual = RiskManager(db).evaluate(order, trading_settings, symbol_mapping, mt5_status, 120)
    assert manual.allowed is True


def test_definitive_failed_order_releases_torum_signal_attempt_for_retry() -> None:
    db = _session()
    config = _config(db, "XAUUSD", "H2")
    confirmation = int(_madrid(1, 18, 30).timestamp())
    config.params_json = {
        **(config.params_json or {}),
        "last_signal_candle_time": confirmation,
        "last_signal_pullback_low_time": confirmation - 300,
        "last_signal_operation_zone_id": "zone-1",
    }
    signal = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        reason="test",
        metadata_json={"confirmation_candle_time": confirmation},
    )

    _release_torum_v1_signal_attempt(config, signal)

    assert "last_signal_candle_time" not in config.params_json
    assert "last_signal_pullback_low_time" not in config.params_json
    assert "last_signal_operation_zone_id" not in config.params_json


def test_daily_reset_yesterday_unlock_does_not_unlock_today() -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)

    status = TorumV1StatusService(db).status_for_user(1, _madrid(2, 11, 5)).assets["XAUEUR"]

    assert status.status == "LOCKED"


def test_unlock_push_is_sent_once_per_symbol_and_day(monkeypatch) -> None:
    db = _session()
    _config(db, "XAUEUR", "H2")
    _two_hour_window(db, "XAUEUR", _madrid(1, 9), open_=100, close=110, low=99, previous_low=90)
    db.add(
        PushSubscription(
            user_id=1,
            endpoint="https://push.example.test/1",
            p256dh="key",
            auth="auth",
            enabled=True,
        )
    )
    db.commit()
    sent: list[tuple[int, str, str]] = []

    def fake_send(self, user_id: int, symbol: str, unlock_day: str) -> tuple[int, int]:
        sent.append((user_id, symbol, unlock_day))
        return 1, 0

    monkeypatch.setattr("app.alerts.push.PushNotificationService.send_torum_v1_unlocked", fake_send)

    first = send_torum_v1_unlock_notifications(db, symbols=["XAUEUR"], at_time=_madrid(1, 11, 5))
    second = send_torum_v1_unlock_notifications(db, symbols=["XAUEUR"], at_time=_madrid(1, 11, 10))

    assert first == 1
    assert second == 0
    assert sent == [(1, "XAUEUR", "2026-05-01")]


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


def test_pullback_down_leg_returns_one_pullback_with_last_low() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99, 99.5),
        _m5_candle(_madrid(1, 9, 5), 99.5, 99.6, 98, 98.5),
        _m5_candle(_madrid(1, 9, 10), 98.5, 98.6, 97, 97.5),
        _m5_candle(_madrid(1, 9, 15), 97.5, 97.6, 96, 96.5),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20)

    assert len(pullbacks) == 1
    assert pullbacks[0].swing_high == 100
    assert pullbacks[0].pullback_low == 96
    assert pullbacks[0].is_live is True


def test_pullback_recovery_then_new_drop_returns_two_segments() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99, 99.5),
        _m5_candle(_madrid(1, 9, 5), 99.5, 99.6, 96, 96.5),
        _m5_candle(_madrid(1, 9, 10), 96.0, 96.3, 96.0, 96.2),
        _m5_candle(_madrid(1, 9, 15), 96.2, 98.0, 97.8, 97.9),
        _m5_candle(_madrid(1, 9, 20), 97.9, 98.0, 97.0, 97.4),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20, recovery_pct=0.10, end_confirmation_bars=1)

    assert len(pullbacks) == 2
    assert pullbacks[0].pullback_low == 96
    assert pullbacks[0].is_live is False
    assert pullbacks[1].swing_high == 98
    assert pullbacks[1].pullback_low == 97
    assert pullbacks[1].is_live is True


def test_pullback_updates_swing_high_before_drop() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 105, 104.9, 104.95),
        _m5_candle(_madrid(1, 9, 10), 104.95, 105, 104.7, 104.8),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20)

    assert len(pullbacks) == 1
    assert pullbacks[0].swing_high == 105
    assert pullbacks[0].pullback_low == 104.7


def test_live_pullback_updates_current_segment_low() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.7, 99.8),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.4,
        live_time=_madrid(1, 9, 9),
    )

    assert len(pullbacks) == 1
    assert pullbacks[0].pullback_low == 99.4
    assert pullbacks[0].pullback_low_time == _madrid(1, 9, 9).astimezone(UTC)
    assert pullbacks[0].is_live is True


def test_live_pullback_keeps_minimum_when_price_rebounds() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.7, 99.8),
    ]

    first = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.4,
        live_time=_madrid(1, 9, 9),
        live_cache_key="test-live-rebound",
    )
    second = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.8,
        live_time=_madrid(1, 9, 10),
        live_cache_key="test-live-rebound",
    )

    assert first[0].pullback_low == 99.4
    assert second[0].pullback_low == 99.4
    assert second[0].pullback_low_time == _madrid(1, 9, 9).astimezone(UTC)


def test_live_pullback_updates_when_new_live_minimum_arrives() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.7, 99.8),
    ]

    detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.4,
        live_time=_madrid(1, 9, 9),
        live_cache_key="test-live-new-low",
    )
    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.2,
        live_time=_madrid(1, 9, 10),
        live_cache_key="test-live-new-low",
    )

    assert pullbacks[0].pullback_low == 99.2
    assert pullbacks[0].pullback_low_time == _madrid(1, 9, 10).astimezone(UTC)


def test_live_pullback_uses_candle_low_when_it_is_lower_than_live_price() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.4, 99.8),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.8,
        live_time=_madrid(1, 9, 9),
    )

    assert pullbacks[0].pullback_low == 99.4
    assert pullbacks[0].pullback_low_time == _madrid(1, 9, 5).astimezone(UTC)


def test_live_pullback_uses_live_price_when_it_is_lower_than_candle_low() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.7, 99.8),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.4,
        live_time=_madrid(1, 9, 9),
    )

    assert pullbacks[0].pullback_low == 99.4
    assert pullbacks[0].pullback_low_time == _madrid(1, 9, 9).astimezone(UTC)


def test_live_pullback_can_start_from_live_low_after_closed_bearish_leg() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.95, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 100, 99.9, 99.7),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.7,
        live_time=_madrid(1, 9, 9),
    )

    assert pullbacks[0].pullback_low == 99.7
    assert pullbacks[0].pullback_low_time == _madrid(1, 9, 9).astimezone(UTC)
    assert pullbacks[0].is_live is True


def test_green_impulse_candle_does_not_create_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.8, 100.2, 99.4, 100.1),
    ]

    assert detect_pullbacks(candles, threshold=0.20) == []


def test_two_green_impulse_candles_do_not_create_pullbacks() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100.4, 99.9, 100.3),
        _m5_candle(_madrid(1, 9, 5), 100.3, 100.8, 100.0, 100.7),
    ]

    assert detect_pullbacks(candles, threshold=0.20) == []


def test_green_hammer_after_bearish_leg_is_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 99.95, 99.4, 99.9),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20)

    assert len(pullbacks) == 1
    assert pullbacks[0].pullback_low == 99.4


def test_pullback_recovery_new_high_preserves_middle_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 99.75, 99.4, 99.5),
        _m5_candle(_madrid(1, 9, 15), 99.5, 100.4, 99.5, 100.2),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20, recovery_pct=0.10, end_confirmation_bars=1)

    assert len(pullbacks) == 1
    assert pullbacks[0].swing_high == 100.0
    assert pullbacks[0].pullback_low == 99.4
    assert pullbacks[0].is_live is False


def test_invalid_peak_extension_keeps_active_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 100.5, 99.65, 99.68),
    ]

    pullbacks = detect_pullbacks(candles, threshold=0.20, recovery_pct=0.10, end_confirmation_bars=1)

    assert len(pullbacks) == 1
    assert pullbacks[0].swing_high == 100.0
    assert pullbacks[0].pullback_low == 99.6
    assert pullbacks[0].is_live is True


def test_same_candle_high_low_does_not_create_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 99.8, 100.5, 99.5, 100.2),
    ]

    assert detect_pullbacks(candles, threshold=0.20) == []


def test_live_price_does_not_create_pullback_without_bearish_leg() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 99.8, 100.5, 99.8, 100.2),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        live_price=99.6,
        live_time=_madrid(1, 9, 2),
    )

    assert pullbacks == []


def test_pullback_debug_payload_returns_one_segment_per_down_leg() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99, 99.5),
        _m5_candle(_madrid(1, 9, 5), 99.5, 99.6, 98, 98.5),
        _m5_candle(_madrid(1, 9, 10), 98.5, 98.6, 97, 97.5),
        _m5_candle(_madrid(1, 9, 15), 97.5, 97.6, 96, 96.5),
    ]

    payload = pullback_debug_payload(candles, {"pullback_threshold_pct": 0.2})

    assert len(payload) == 1
    assert payload[0]["pullback_low"] == 96
    assert payload[0]["is_live"] is True


def test_pullback_zero_threshold_detects_small_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.96, 99.99),
        _m5_candle(_madrid(1, 9, 5), 99.99, 100.0, 99.95, 99.98),
    ]

    payload = pullback_debug_payload(candles, {"pullback_min_pct": 0, "pullback_max_count": 10})

    assert len(payload) == 1
    assert payload[0]["pullback_pct"] < 0.2
    assert payload[0]["threshold_touched"] is False


def test_pullback_payload_returns_only_latest_max_count() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.5, 99.6),
        _m5_candle(_madrid(1, 9, 5), 99.6, 99.8, 99.6, 99.75),
        _m5_candle(_madrid(1, 9, 10), 100.8, 101, 100.7, 100.9),
        _m5_candle(_madrid(1, 9, 15), 100.9, 101, 100.5, 100.6),
        _m5_candle(_madrid(1, 9, 20), 100.6, 100.9, 100.6, 100.8),
        _m5_candle(_madrid(1, 9, 25), 101.8, 102, 101.7, 101.9),
        _m5_candle(_madrid(1, 9, 30), 101.9, 102, 101.5, 101.6),
    ]

    payload = pullback_debug_payload(
        candles,
        {"pullback_min_pct": 0, "pullback_max_count": 2, "pullback_recovery_pct": 0.01},
    )

    assert len(payload) == 2
    assert payload[0]["swing_high"] == 101
    assert payload[1]["swing_high"] == 102


def test_pullback_starts_at_later_real_high_inside_same_down_leg() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 5), 99.7, 101.0, 100.6, 100.7),
        _m5_candle(_madrid(1, 9, 10), 100.7, 100.8, 99.0, 99.2),
        _m5_candle(_madrid(1, 9, 15), 99.2, 99.4, 98.8, 99.0),
    ]

    payload = pullback_debug_payload(
        candles,
        {
            "pullback_threshold_pct": 0.2,
            "pullback_lookback_bars": 12,
            "pullback_swing_confirm_bars": 1,
            "pullback_allow_peak_extension": True,
        },
    )

    assert len(payload) == 1
    assert payload[0]["swing_high"] == 101.0
    assert payload[0]["swing_high_time"] == int(_madrid(1, 9, 5).timestamp())
    assert payload[0]["pullback_low"] == 98.8
    assert payload[0]["pullback_low_time"] >= payload[0]["swing_high_time"]


def test_pullback_peak_extension_can_move_start_three_candles_right() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.5, 99.7),
        _m5_candle(_madrid(1, 9, 5), 99.7, 99.9, 99.6, 99.85),
        _m5_candle(_madrid(1, 9, 10), 99.85, 100.0, 99.8, 100.0),
        _m5_candle(_madrid(1, 9, 15), 100.5, 101.0, 100.2, 100.4),
        _m5_candle(_madrid(1, 9, 20), 100.4, 102.0, 101.2, 101.5),
        _m5_candle(_madrid(1, 9, 25), 101.5, 103.0, 102.0, 102.3),
        _m5_candle(_madrid(1, 9, 30), 102.3, 102.5, 101.0, 101.2),
    ]

    payload = pullback_debug_payload(
        candles,
        {
            "pullback_threshold_pct": 0.2,
            "pullback_lookback_bars": 12,
            "pullback_swing_confirm_bars": 1,
            "pullback_allow_peak_extension": True,
        },
    )

    assert len(payload) == 1
    assert payload[-1]["swing_high"] == 103.0
    assert payload[-1]["swing_high_time"] == int(_madrid(1, 9, 25).timestamp())
    assert payload[-1]["pullback_low"] == 101.0


def test_peak_extension_still_moves_when_new_high_has_later_drop() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 100.5, 99.7, 100.3),
        _m5_candle(_madrid(1, 9, 15), 100.3, 100.4, 99.8, 99.9),
    ]

    pullbacks = detect_pullbacks(
        candles,
        threshold=0.20,
        recovery_pct=5.0,
        end_confirmation_bars=1,
        allow_peak_extension=True,
    )

    assert len(pullbacks) == 1
    assert pullbacks[0].swing_high == 100.5
    assert pullbacks[0].pullback_low == 99.8


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
    assert decision.reason == "pullback_low_outside_operation_zone"


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


def test_torum_buy_zone_extends_below_rectangle_lower_edge() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    # The rectangle is visually 100.0-101.0, but for a BUY Torum zone the
    # upper edge (101.0) is the only vertical boundary. Both the pullback low
    # and the executable confirmation price are below the visual lower edge.
    zone = TorumV1OperationZone(
        "z1",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        100.0,
        101.0,
    )

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
        current_price=99.9,
    )

    assert decision.should_buy is True
    assert decision.zone is zone
    assert decision.metadata is not None
    assert decision.metadata["confirmation_price_inside_operation_zone"] is True


def test_current_broker_clock_prevents_three_hour_old_confirmation_entry() -> None:
    stale_peak = datetime(2026, 7, 31, 10, 55, tzinfo=UTC)
    stale_low = stale_peak + timedelta(minutes=5)
    stale_confirmation = stale_peak + timedelta(minutes=10)
    current_broker_confirmation = datetime(2026, 7, 31, 14, 5, tzinfo=UTC)
    candles = [
        _m5_candle(stale_peak, 100.0, 100.0, 99.9, 99.95),
        _m5_candle(stale_low, 99.95, 99.96, 99.7, 99.8),
        _m5_candle(stale_confirmation, 99.8, 99.95, 99.75, 99.9),
        _m5_candle(current_broker_confirmation, 99.9, 99.92, 99.6, 99.65),
    ]
    zone = TorumV1OperationZone(
        "z1",
        "rectangle",
        int(datetime(2026, 7, 31, 0, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 8, 1, 0, 0, tzinfo=UTC).timestamp()),
        99.0,
        101.0,
    )
    params = {"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12}

    stale_clock_decision = should_buy_torum_v1(
        symbol="XAUEUR",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=datetime(2026, 7, 31, 11, 10, 30, tzinfo=UTC),
    )
    broker_clock_decision = should_buy_torum_v1(
        symbol="XAUEUR",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=datetime(2026, 7, 31, 14, 10, 30, tzinfo=UTC),
    )

    assert stale_clock_decision.should_buy is True
    assert stale_clock_decision.confirmation_candle_time == stale_confirmation
    assert broker_clock_decision.should_buy is False
    assert broker_clock_decision.reason == "waiting_bullish_confirmation"


def test_pullback_entry_min_pct_blocks_small_pullback_inside_zone() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.81, 99.84),
        _m5_candle(_madrid(1, 9, 10), 99.84, 99.95, 99.82, 99.94),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99, 101)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "current_pullback_below_entry_min"
    assert decision.metadata["pullback_pct"] < 0.2


def test_only_current_pullback_can_trigger_entry_not_previous_valid_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.65),
        _m5_candle(_madrid(1, 9, 10), 99.65, 99.82, 99.64, 99.8),
        _m5_candle(_madrid(1, 9, 15), 99.8, 100.0, 99.79, 99.95),
        _m5_candle(_madrid(1, 9, 20), 99.95, 99.96, 99.85, 99.86),
        _m5_candle(_madrid(1, 9, 25), 99.86, 99.98, 99.86, 99.97),
    ]
    zone = TorumV1OperationZone(
        "z1",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        99.0,
        101.0,
    )

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 31),
    )

    assert decision.should_buy is False
    assert decision.reason == "current_pullback_below_entry_min"
    assert decision.pullback is not None
    assert decision.pullback.swing_high_time == _madrid(1, 9, 15)
    assert decision.pullback.confirmation_candle_time == _madrid(1, 9, 25)
    assert decision.pullback.pullback_pct < 0.2


def test_pullback_low_inside_zone_blocks_when_confirmation_outside_by_default() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99.65, 99.85)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "confirmation_price_outside_operation_zone"
    assert decision.zone is zone
    assert decision.metadata["confirmation_inside_operation_zone"] is False
    assert decision.metadata["pullback_low_time"] == int(_madrid(1, 9, 5).timestamp())


def test_pullback_low_inside_zone_can_allow_confirmation_outside_from_settings() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99.65, 99.85)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "operation_zone_allow_confirmation_price_outside": True,
        },
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is True
    assert decision.reason == "buy_pullback_inside_zone_confirmation_price_outside_allowed"
    assert decision.zone is zone
    assert decision.metadata["entry_setup"] == "pullback_low_inside_zone_confirmation_price_outside_allowed"
    assert decision.metadata["confirmation_inside_operation_zone"] is False
    assert decision.metadata["confirmation_time_inside_operation_zone"] is True
    assert decision.metadata["confirmation_price_inside_operation_zone"] is False


def test_confirmation_price_exception_does_not_ignore_rectangle_time() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone(
        "z1",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 9, 9).timestamp()),
        99.65,
        100.0,
    )

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "operation_zone_allow_confirmation_price_outside": True,
        },
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "confirmation_time_outside_operation_zone"
    assert decision.metadata["confirmation_time_inside_operation_zone"] is False


def test_current_executable_price_must_also_be_inside_zone_in_strict_mode() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99.65, 100.0)

    strict = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
        current_price=100.2,
    )
    permissive = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "operation_zone_allow_confirmation_price_outside": True,
        },
        now=_madrid(1, 9, 16),
        current_price=100.2,
    )

    assert strict.should_buy is False
    assert strict.reason == "confirmation_price_outside_operation_zone"
    assert strict.metadata["executable_price"] == 100.2
    assert permissive.should_buy is True
    assert permissive.reason == "buy_pullback_inside_zone_confirmation_price_outside_allowed"


def test_pullback_recovery_new_high_can_trigger_buy_from_zone_low() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 99.75, 99.4, 99.5),
        _m5_candle(_madrid(1, 9, 15), 99.5, 100.4, 99.5, 100.2),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9, 5).timestamp()), int(_madrid(1, 9, 25).timestamp()), 99.3, 99.5)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "operation_zone_allow_confirmation_price_outside": True,
        },
        now=_madrid(1, 9, 21),
    )

    assert decision.should_buy is True
    assert decision.metadata["pullback_low"] == 99.4
    assert decision.metadata["operation_zone_id"] == "z1"


def test_should_buy_uses_latest_valid_pullback() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.6, 99.7),
        _m5_candle(_madrid(1, 9, 10), 99.7, 100.2, 99.7, 100.1),
        _m5_candle(_madrid(1, 9, 15), 100.1, 101.0, 100.1, 100.9),
        _m5_candle(_madrid(1, 9, 20), 100.9, 100.95, 100.6, 100.7),
        _m5_candle(_madrid(1, 9, 25), 100.7, 101.2, 100.7, 101.0),
    ]
    zone = TorumV1OperationZone("latest", "rectangle", int(_madrid(1, 9, 20).timestamp()), int(_madrid(1, 9, 35).timestamp()), 100.5, 100.7)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "operation_zone_allow_confirmation_price_outside": True,
        },
        now=_madrid(1, 9, 31),
    )

    assert decision.should_buy is True
    assert decision.metadata["pullback_low"] == 100.6
    assert decision.metadata["operation_zone_id"] == "latest"


def test_confirmation_inside_zone_but_pullback_low_outside_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9, 10).timestamp()), int(_madrid(1, 9, 20).timestamp()), 99.85, 100.0)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "pullback_low_outside_operation_zone"


def test_pullback_low_inside_by_price_but_outside_by_time_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9, 6).timestamp()), int(_madrid(1, 9, 20).timestamp()), 99.65, 99.75)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "pullback_low_outside_operation_zone"


def test_pullback_low_inside_by_time_but_outside_by_price_no_buy() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9, 4).timestamp()), int(_madrid(1, 9, 6).timestamp()), 98.0, 99.0)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.2, "pullback_lookback_bars": 12},
        now=_madrid(1, 9, 16),
    )

    assert decision.should_buy is False
    assert decision.reason == "pullback_low_outside_operation_zone"


def test_pullback_low_zone_helper_accepts_open_ended_time2() -> None:
    pullback = detect_pullbacks(
        [
            _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
            _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
            _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
        ],
        threshold=0.2,
    )[0]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), None, 99.65, 99.75)

    assert is_pullback_low_inside_operation_zone(pullback, zone) is True


def test_runner_detects_duplicate_torum_setup_signal() -> None:
    db = _session()
    user = db.get(User, 1)
    assert user is not None
    config = _config(db, "XAUUSD")
    metadata = {
        "confirmation_candle_time": int(_madrid(1, 16).timestamp()),
        "pullback_low_time": int(_madrid(1, 15, 45).timestamp()),
        "operation_zone_id": "zone-1",
    }
    previous = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=user.id,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.72,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json=metadata,
        status="ORDER_EXECUTED",
    )
    current = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=user.id,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.72,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json=metadata,
        status="GENERATED",
    )
    db.add_all([previous, current])
    db.commit()
    db.refresh(previous)
    db.refresh(current)

    duplicate = StrategyRunner(db)._previous_torum_v1_setup_signal(current)

    assert duplicate is not None
    assert duplicate.id == previous.id


def test_support_level_uses_executable_price_inside_visual_band() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99.0, 101.0)
    s1 = TorumV1SupportZone("s1", 1, 99.9, 99.85, 99.95, 0.2)
    s2 = TorumV1SupportZone("s2", 2, 99.9, 99.85, 99.95, 0.2)
    s3 = TorumV1SupportZone("s3", 3, 99.9, 99.85, 99.95, 0.2)

    base_params = {
        "pullback_entry_min_pct": 0.2,
        "pullback_lookback_bars": 12,
        "one_position_per_symbol": False,
    }
    s1_decision = should_buy_torum_v1(symbol="XAUUSD", candles_m5=candles, operation_zones=[zone], support_zones=[s1], params=base_params, now=_madrid(1, 9, 16), current_price=99.9)
    s2_decision = should_buy_torum_v1(symbol="XAUUSD", candles_m5=candles, operation_zones=[zone], support_zones=[s2], params=base_params, now=_madrid(1, 9, 16), current_price=99.9)
    s3_decision = should_buy_torum_v1(symbol="XAUUSD", candles_m5=candles, operation_zones=[zone], support_zones=[s3], params=base_params, now=_madrid(1, 9, 16), current_price=99.9)

    assert s1_decision.metadata["desired_multiplier"] == 1
    assert s2_decision.metadata["desired_multiplier"] == 2
    assert s3_decision.metadata["desired_multiplier"] == 3
    assert s3_decision.metadata["support_reference"] == "ENTRY_PRICE_VISUAL_ZONE"
    assert s3_decision.metadata["support_reference_price"] == 99.9


def test_support_multiplier_does_not_expand_outside_visual_band() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone("z1", "rectangle", int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()), 99.0, 101.0)
    support = TorumV1SupportZone("s3", 3, 99.7, 99.65, 99.75, 0.2)

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        support_zones=[support],
        params={
            "pullback_entry_min_pct": 0.2,
            "pullback_lookback_bars": 12,
            "one_position_per_symbol": False,
            "support_reference": "PULLBACK_LOW",
            "support_max_distance_pct": 99.0,
        },
        now=_madrid(1, 9, 16),
        current_price=99.9,
    )

    assert decision.should_buy is True
    assert decision.support is None
    assert decision.metadata["desired_multiplier"] == 1
    assert decision.metadata["support_reference"] == "ENTRY_PRICE_VISUAL_ZONE"


def test_doji_can_confirm_current_pullback_when_enabled() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100, 100, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.9, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone(
        "z1",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        99,
        101,
    )

    accepted = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"confirmation_ignore_doji": True},
        now=_madrid(1, 9, 16),
    )
    rejected = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={"confirmation_ignore_doji": False},
        now=_madrid(1, 9, 16),
    )

    assert accepted.should_buy is True
    assert rejected.should_buy is False
    assert rejected.reason == "waiting_bullish_confirmation"


def test_ath_zone_never_promotes_a_simple_setup_to_double() -> None:
    db = _session()
    set_symbol_ath_level(db, "XAUUSD", "manual", 6000)

    legacy_enabled = _torum_v1_desired_multiplier_for_ath_zone(
        db,
        symbol="XAUUSD",
        current_price=5000,
        params={"ath_green_prefer_x2_entries": True},
        desired_multiplier=1,
    )
    already_double = _torum_v1_desired_multiplier_for_ath_zone(
        db,
        symbol="XAUUSD",
        current_price=5000,
        params={"ath_green_prefer_x2_entries": False},
        desired_multiplier=2,
    )

    assert legacy_enabled == 1
    assert already_double == 2


def test_no_support_is_simple_even_if_s1_multiplier_was_customized() -> None:
    assert desired_multiplier_for_support(
        None,
        [],
        params={"support_s1_multiplier": 3},
    ) == 1
    assert desired_multiplier_for_support(
        None,
        [],
        params={"support_s1_multiplier": 3},
        zone_default_multiplier=2,
    ) == 2
    assert desired_multiplier_for_support(
        None,
        [],
        params={"support_s1_multiplier": 1},
        zone_default_multiplier=3,
    ) == 3


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


def test_rectangle_torum_zone_can_request_x2_and_legacy_manual_zone_is_ignored() -> None:
    common_metadata = {
        "torum_v1_zone_enabled": True,
        "torum_v1_default_double_enabled": True,
        "direction": "BUY",
    }
    legacy_manual = ChartDrawing(
        id="legacy-manual", user_id=1, internal_symbol="XAUUSD", timeframe="M5",
        drawing_type="manual_zone", name=None,
        payload_json={
            "time1": int(_madrid(1, 9).timestamp()),
            "time2": int(_madrid(1, 10).timestamp()),
            "price_min": 99.0, "price_max": 101.0, "direction": "BUY",
        },
        style_json={}, metadata_json=common_metadata, locked=False, visible=True, source="MANUAL",
    )
    rectangle = ChartDrawing(
        id="rectangle-x2", user_id=1, internal_symbol="XAUUSD", timeframe="M5",
        drawing_type="rectangle", name=None,
        payload_json={
            "time1": int(_madrid(1, 9).timestamp()),
            "time2": int(_madrid(1, 10).timestamp()),
            "price1": 99.0, "price2": 101.0,
        },
        style_json={}, metadata_json=common_metadata, locked=False, visible=True, source="MANUAL",
    )

    zones = operation_zones_from_drawings([legacy_manual, rectangle])

    assert [zone.drawing_id for zone in zones] == ["rectangle-x2"]
    assert zones[0].default_multiplier == 2


def test_rectangle_torum_zone_can_request_x3_with_new_multiplier_metadata() -> None:
    drawing = ChartDrawing(
        id="rectangle-x3",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        drawing_type="rectangle",
        name=None,
        payload_json={
            "time1": int(_madrid(1, 9).timestamp()),
            "time2": int(_madrid(1, 10).timestamp()),
            "price1": 99.0,
            "price2": 101.0,
        },
        style_json={},
        metadata_json={
            "torum_v1_zone_enabled": True,
            "torum_v1_default_multiplier": 3,
            "direction": "BUY",
        },
        locked=False,
        visible=True,
        source="MANUAL",
    )

    zones = operation_zones_from_drawings([drawing])

    assert len(zones) == 1
    assert zones[0].default_multiplier == 3


def test_rectangle_torum_zone_x3_applies_without_support_and_support_keeps_precedence() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone(
        "rectangle-x3", "rectangle",
        int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()),
        99.0, 101.0, default_multiplier=3,
    )
    no_support = should_buy_torum_v1(
        symbol="XAUUSD", candles_m5=candles, operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.20},
        now=_madrid(1, 9, 16), current_price=99.9,
    )
    s2 = TorumV1SupportZone(
        drawing_id="s2", level=2, price=99.9, lower_price=99.7, upper_price=100.0, opacity=0.2,
    )
    with_support = should_buy_torum_v1(
        symbol="XAUUSD", candles_m5=candles, operation_zones=[zone], support_zones=[s2],
        params={"pullback_entry_min_pct": 0.20},
        now=_madrid(1, 9, 16), current_price=99.9,
    )

    assert no_support.should_buy is True
    assert no_support.metadata is not None and no_support.metadata["desired_multiplier"] == 3
    assert with_support.should_buy is True
    assert with_support.metadata is not None and with_support.metadata["desired_multiplier"] == 2


def test_rectangle_torum_zone_x2_applies_only_without_visual_support() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 100.0, 100.0, 99.9, 99.95),
        _m5_candle(_madrid(1, 9, 5), 99.95, 99.96, 99.7, 99.8),
        _m5_candle(_madrid(1, 9, 10), 99.8, 99.95, 99.75, 99.9),
    ]
    zone = TorumV1OperationZone(
        "rectangle-x2", "rectangle",
        int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()),
        99.0, 101.0, default_multiplier=2,
    )
    no_support = should_buy_torum_v1(
        symbol="XAUUSD", candles_m5=candles, operation_zones=[zone],
        params={"pullback_entry_min_pct": 0.20},
        now=_madrid(1, 9, 16), current_price=99.9,
    )
    s3 = TorumV1SupportZone(
        drawing_id="s3", level=3, price=99.9, lower_price=99.7, upper_price=100.0, opacity=0.2,
    )
    with_support = should_buy_torum_v1(
        symbol="XAUUSD", candles_m5=candles, operation_zones=[zone], support_zones=[s3],
        params={"pullback_entry_min_pct": 0.20},
        now=_madrid(1, 9, 16), current_price=99.9,
    )

    assert no_support.should_buy is True
    assert no_support.metadata is not None and no_support.metadata["desired_multiplier"] == 2
    assert with_support.should_buy is True
    assert with_support.metadata is not None and with_support.metadata["desired_multiplier"] == 3


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
        "operation_zone_allow_confirmation_price_outside": True,
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
    StrategyCatalogService(db).register_defaults()

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


def test_torum_v1_usd_strong_snapshot_blocks_bot_signal() -> None:
    db = _session()
    config = _config(db, "XAUUSD", "H2")
    config.params_json = {
        **config.params_json,
        "enable_operation_zones": True,
        "require_zone": True,
        "operation_zone_allow_confirmation_price_outside": True,
        "pullback_entry_min_pct": 0.2,
        "pullback_lookback_bars": 12,
        "usd_strength_filter_enabled": True,
    }
    db.add(
        DollarStrengthSnapshot(
            symbol="DXY",
            dxy_value=101.0,
            sma30=100.0,
            difference=1.0,
            state="STRONG",
            trading_allowed=False,
            reason="dxy_above_sma30",
            slope_days=3,
            slope_pct=0.5,
            strong_drop_override_active=False,
            source="synthetic_mt5",
            missing_symbols=[],
            symbols_used=["EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF"],
            stale=False,
        )
    )
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
    StrategyCatalogService(db).register_defaults()

    result = StrategyRunner(db).run_config(config, db.get(User, 1))

    assert result.ok is False
    assert result.order_id is None
    assert result.reasons == ["usd_strength_blocked"]
    assert result.signal is not None
    stored_signal = db.query(StrategySignal).order_by(StrategySignal.id.desc()).first()
    assert stored_signal is not None
    assert stored_signal.metadata_json["usd_strength_state"] == "STRONG"


def test_entry_does_not_split_subthreshold_bounces_and_first_bullish_candle_confirms() -> None:
    """A small green bounce before 0.20% must not reset the current setup.

    Once the accumulated correction reaches the configured minimum, the first
    bullish closed candle confirms by default even if its rebound from the low
    is smaller than the visual 0.10% recovery setting.
    """

    candles = [
        _m5_candle(_madrid(1, 9), 99.95, 100.00, 99.94, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 99.99, 99.85, 99.88),
        _m5_candle(_madrid(1, 9, 10), 99.88, 99.94, 99.86, 99.93),
        _m5_candle(_madrid(1, 9, 15), 99.93, 99.94, 99.70, 99.72),
        _m5_candle(_madrid(1, 9, 20), 99.72, 99.76, 99.71, 99.75),
    ]
    zone = TorumV1OperationZone(
        "z-entry-current",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        99.0,
        101.0,
    )

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.20,
            "pullback_recovery_pct": 0.10,
            "pullback_lookback_bars": 12,
        },
        now=_madrid(1, 9, 26),
        current_price=99.75,
    )

    assert decision.should_buy is True
    assert decision.pullback is not None
    assert decision.pullback.swing_high == 100.0
    assert decision.pullback.pullback_low == 99.70
    assert decision.pullback.pullback_pct >= 0.20
    assert decision.pullback.confirmation_candle_time == _madrid(1, 9, 20)
    assert decision.metadata["pullback_entry_recovery_pct"] == 0.0


def test_optional_entry_recovery_filter_is_only_applied_when_configured() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 99.95, 100.00, 99.94, 99.98),
        _m5_candle(_madrid(1, 9, 5), 99.98, 99.99, 99.70, 99.72),
        # Bullish, but only a 0.05% rebound from the pullback low.
        _m5_candle(_madrid(1, 9, 10), 99.72, 99.76, 99.71, 99.75),
        # This later candle finally recovers more than 0.10% from 99.70.
        _m5_candle(_madrid(1, 9, 15), 99.75, 99.83, 99.74, 99.82),
    ]
    zone = TorumV1OperationZone(
        "z-entry-recovery",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        99.0,
        101.0,
    )
    params = {
        "pullback_entry_min_pct": 0.20,
        "pullback_entry_recovery_pct": 0.10,
        "pullback_lookback_bars": 12,
    }

    too_early = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles[:3],
        operation_zones=[zone],
        params=params,
        now=_madrid(1, 9, 16),
        current_price=99.75,
    )
    recovered = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=_madrid(1, 9, 21),
        current_price=99.82,
    )

    assert too_early.should_buy is False
    assert too_early.reason == "missing_current_pullback"
    assert recovered.should_buy is True
    assert recovered.pullback is not None
    assert recovered.pullback.confirmation_candle_time == _madrid(1, 9, 15)
    assert recovered.metadata["pullback_entry_recovery_pct"] == 0.10



def test_bullish_candle_that_marks_pullback_low_can_confirm_the_entry() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        # This candle creates the lowest low and closes bullish. It must confirm
        # the setup at its close so the order can be sent on the following bar.
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "zone-same-low-confirmation",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        4000.0,
        4100.0,
    )

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.20,
            "pullback_entry_recovery_pct": 0.0,
            "pullback_lookback_bars": 12,
        },
        now=_madrid(1, 9, 21),
        current_price=4034.0,
    )

    assert decision.should_buy is True
    assert decision.pullback is not None
    assert decision.pullback.pullback_low == 4028.0
    assert decision.pullback.pullback_low_time == _madrid(1, 9, 15)
    assert decision.pullback.confirmation_candle_time == _madrid(1, 9, 15)


def test_successful_entry_starts_a_new_pullback_cycle_from_its_confirmation_candle() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        # First pullback: low and bullish confirmation on the same candle.
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
        # Entry is executed after the prior candle closes. This candle creates
        # the swing high from which the second pullback must be measured.
        _m5_candle(_madrid(1, 9, 20), 4034.0, 4042.0, 4033.0, 4040.0),
        _m5_candle(_madrid(1, 9, 25), 4040.0, 4040.5, 4030.0, 4031.0),
        # Second pullback: new low and bullish confirmation.
        _m5_candle(_madrid(1, 9, 30), 4030.5, 4036.0, 4029.0, 4035.0),
    ]
    zone = TorumV1OperationZone(
        "zone-cycle-reset",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        4000.0,
        4100.0,
    )
    base_params = {
        "pullback_entry_min_pct": 0.20,
        "pullback_entry_recovery_pct": 0.0,
        "pullback_lookback_bars": 12,
    }

    first = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles[:4],
        operation_zones=[zone],
        params=base_params,
        now=_madrid(1, 9, 21),
        current_price=4034.0,
    )
    assert first.should_buy is True
    assert first.pullback is not None
    assert first.pullback.swing_high == 4050.0
    assert first.pullback.pullback_low == 4028.0

    boundary = int(_madrid(1, 9, 15).timestamp())
    second = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            **base_params,
            "last_signal_candle_time": boundary,
            "last_executed_entry_candle_time": boundary,
            "executed_entry_cycle_boundaries": [boundary],
        },
        now=_madrid(1, 9, 36),
        current_price=4035.0,
    )

    assert second.should_buy is True
    assert second.pullback is not None
    assert second.pullback.swing_high == 4042.0
    assert second.pullback.swing_high_time == _madrid(1, 9, 20)
    assert second.pullback.pullback_low == 4029.0
    assert second.pullback.pullback_low_time == _madrid(1, 9, 30)
    assert second.pullback.confirmation_candle_time == _madrid(1, 9, 30)


def test_pullback_debug_keeps_completed_cycle_and_draws_new_cycle_separately() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
        _m5_candle(_madrid(1, 9, 20), 4034.0, 4042.0, 4033.0, 4040.0),
        _m5_candle(_madrid(1, 9, 25), 4040.0, 4040.5, 4030.0, 4031.0),
        _m5_candle(_madrid(1, 9, 30), 4030.5, 4036.0, 4029.0, 4035.0),
    ]
    boundary = int(_madrid(1, 9, 15).timestamp())

    payload = pullback_debug_payload(
        candles,
        {
            "pullback_min_pct": 0.20,
            "pullback_recovery_pct": 0.10,
            "pullback_lookback_bars": 12,
            "executed_entry_cycle_boundaries": [boundary],
            "last_executed_entry_candle_time": boundary,
            "pullback_live_update_enabled": False,
        },
    )

    assert len(payload) == 2
    assert payload[0]["swing_high"] == 4050.0
    assert payload[0]["pullback_low"] == 4028.0
    assert payload[1]["swing_high"] == 4042.0
    assert payload[1]["pullback_low"] == 4029.0


def test_runner_records_pullback_cycle_only_for_executed_torum_entry() -> None:
    db = _session()
    config = _config(db, "XAUUSD")
    confirmation_time = int(_madrid(1, 9, 15).timestamp())
    signal = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.72,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json={"confirmation_candle_time": confirmation_time},
        status="ORDER_EXECUTED",
    )

    _record_torum_v1_executed_entry_cycle(config, signal, order_id=123)

    assert config.params_json["last_executed_entry_candle_time"] == confirmation_time
    assert config.params_json["last_executed_entry_order_id"] == 123
    assert config.params_json["executed_entry_cycle_boundaries"] == [confirmation_time]


def test_aggregated_unlock_diagnostic_uses_window_boundaries() -> None:
    from app.strategies.torum_v1 import AggregatedCandle, _aggregated_candle_diagnostic_payload

    start = _madrid(1, 9).astimezone(UTC)
    end = _madrid(1, 11).astimezone(UTC)
    payload = _aggregated_candle_diagnostic_payload(
        AggregatedCandle(
            start_time=start,
            end_time=end,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
        )
    )

    assert payload is not None
    assert payload["start_time"] == start
    assert payload["end_time"] == end
    assert "time" not in payload
    assert payload["bullish"] is True


def test_auto_runner_selects_only_latest_enabled_config_per_execution_scope() -> None:
    from app.strategies.auto_runner import _latest_configs_by_execution_scope

    old_xaueur = SimpleNamespace(
        id=3,
        user_id=1,
        strategy_key="torum_v1",
        internal_symbol="XAUEUR",
        mode="DEMO",
        revision=1,
    )
    current_xaueur = SimpleNamespace(
        id=5,
        user_id=1,
        strategy_key="torum_v1",
        internal_symbol="XAUEUR",
        mode="DEMO",
        revision=13,
    )
    live_xaueur = SimpleNamespace(
        id=6,
        user_id=1,
        strategy_key="torum_v1",
        internal_symbol="XAUEUR",
        mode="LIVE",
        revision=2,
    )

    selected, duplicates = _latest_configs_by_execution_scope(
        [old_xaueur, current_xaueur, live_xaueur]
    )

    assert [item.id for item in selected] == [5]
    assert [item.id for item in duplicates] == [3, 6]


def test_enabling_new_torum_config_deactivates_every_other_mode_for_symbol() -> None:
    db = _session()
    service = StrategyCatalogService(db)
    paper = service.create_config(
        StrategyConfigCreate(
            strategy_key="torum_v1",
            internal_symbol="XAUUSD",
            timeframe="M5",
            enabled=True,
            mode="PAPER",
            params_json={},
        ),
        user_id=1,
    )
    live = service.create_config(
        StrategyConfigCreate(
            strategy_key="torum_v1",
            internal_symbol="XAUUSD",
            timeframe="M5",
            enabled=True,
            mode="LIVE",
            params_json={},
        ),
        user_id=1,
    )

    db.refresh(paper)
    db.refresh(live)
    assert paper.enabled is False
    assert live.enabled is True


def test_switching_enabled_torum_config_is_single_active_revision() -> None:
    db = _session()
    service = StrategyCatalogService(db)
    first = service.create_config(
        StrategyConfigCreate(
            strategy_key="torum_v1",
            internal_symbol="XAUEUR",
            timeframe="M5",
            enabled=True,
            mode="PAPER",
            params_json={},
        ),
        user_id=1,
    )
    second = service.create_config(
        StrategyConfigCreate(
            strategy_key="torum_v1",
            internal_symbol="XAUEUR",
            timeframe="M5",
            enabled=False,
            mode="DEMO",
            params_json={},
        ),
        user_id=1,
    )

    service.update_config(
        second,
        StrategyConfigUpdate(enabled=True, expected_revision=second.revision),
        user_id=1,
    )

    db.refresh(first)
    db.refresh(second)
    assert first.enabled is False
    assert second.enabled is True


def test_strategy_context_ignores_wrong_mode_and_unidentified_mt5_ghost_positions() -> None:
    from app.positions.models import Position
    from app.strategies.engine import StrategyContextBuilder

    db = _session()
    config = _config(db, "XAUEUR")
    config.mode = "DEMO"
    db.commit()

    def add_position(*, mode: str, ticket: int | None, identifier: int | None) -> Position:
        order = Order(
            user_id=1,
            internal_symbol="XAUEUR",
            broker_symbol="XAUEUR",
            mode=mode,
            side="BUY",
            order_type="MARKET",
            volume=0.03,
            status="EXECUTED",
            source="STRATEGY",
            strategy_key="torum_v1",
        )
        db.add(order)
        db.flush()
        position = Position(
            user_id=1,
            order_id=order.id,
            internal_symbol="XAUEUR",
            broker_symbol="XAUEUR",
            mode=mode,
            side="BUY",
            volume=0.03,
            open_price=3500.0,
            status="OPEN",
            mt5_position_ticket=ticket,
            mt5_position_identifier=identifier,
            opened_at=datetime.now(UTC),
        )
        db.add(position)
        db.flush()
        return position

    valid = add_position(mode="DEMO", ticket=None, identifier=987654)
    add_position(mode="DEMO", ticket=None, identifier=None)
    add_position(mode="PAPER", ticket=None, identifier=None)
    db.commit()

    positions = StrategyContextBuilder(db)._open_positions(config)

    assert [position.id for position in positions] == [valid.id]


def test_risk_exposure_accepts_persistent_mt5_position_identifier() -> None:
    from app.strategies.ath import _is_live_bot_position

    position = SimpleNamespace(
        status="OPEN",
        closed_at=None,
        close_price=None,
        mode="DEMO",
        mt5_position_ticket=None,
        mt5_position_identifier=123456,
    )

    assert _is_live_bot_position(position) is True


def test_two_consecutive_s3_setups_request_triple_after_entry_cycle_reset() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
        _m5_candle(_madrid(1, 9, 20), 4034.0, 4042.0, 4033.0, 4040.0),
        _m5_candle(_madrid(1, 9, 25), 4040.0, 4040.5, 4030.0, 4031.0),
        _m5_candle(_madrid(1, 9, 30), 4030.5, 4036.0, 4029.0, 4035.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        4000.0,
        4100.0,
    )
    support = TorumV1SupportZone(
        drawing_id="support-s3",
        level=3,
        price=4030.0,
        lower_price=4000.0,
        upper_price=4100.0,
        enabled=True,
        opacity=0.2,
    )
    params = {
        "pullback_entry_min_pct": 0.20,
        "pullback_entry_recovery_pct": 0.0,
        "pullback_lookback_bars": 12,
        "support_reference": "ENTRY_PRICE",
        "support_s3_multiplier": 3,
        "one_position_per_symbol": True,
    }

    first = should_buy_torum_v1(
        symbol="XAUEUR",
        candles_m5=candles[:4],
        operation_zones=[zone],
        support_zones=[support],
        params=params,
        now=_madrid(1, 9, 21),
        current_price=4034.0,
        open_positions=[],
    )
    assert first.should_buy is True
    assert first.support is not None and first.support.level == 3
    assert first.metadata["desired_multiplier"] == 3

    first_boundary = int(_madrid(1, 9, 15).timestamp())
    second = should_buy_torum_v1(
        symbol="XAUEUR",
        candles_m5=candles,
        operation_zones=[zone],
        support_zones=[support],
        params={
            **params,
            "last_signal_candle_time": first_boundary,
            "last_executed_entry_candle_time": first_boundary,
            "executed_entry_cycle_boundaries": [first_boundary],
        },
        now=_madrid(1, 9, 36),
        current_price=4035.0,
        open_positions=[],
    )
    assert second.should_buy is True
    assert second.support is not None and second.support.level == 3
    assert second.metadata["desired_multiplier"] == 3
    assert second.pullback is not None
    assert second.pullback.swing_high == 4042.0


def test_third_entry_spacing_keeps_first_and_second_entries_unrestricted() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        4000.0,
        4100.0,
    )
    first_open_position = SimpleNamespace(
        open_price=4045.0,
        order_id=101,
        opened_at=_madrid(1, 9),
    )
    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.20,
            "pullback_entry_recovery_pct": 0.0,
            "pullback_lookback_bars": 12,
            "third_entry_spacing_enabled": True,
            "third_entry_min_distance_pct": 0.20,
            "executed_entry_price_ladder": [
                {
                    "order_id": 101,
                    "confirmation_candle_time": int(_madrid(1, 8, 30).timestamp()),
                    "executed_price": 4045.0,
                }
            ],
        },
        now=_madrid(1, 9, 21),
        current_price=4034.0,
        open_positions=[first_open_position],
    )

    assert decision.should_buy is True
    assert decision.metadata is not None
    assert decision.metadata["entry_ladder_count"] == 1
    assert decision.metadata["third_entry_spacing_applied"] is False


def test_entry_spacing_defaults_are_enabled_and_legacy_single_position_guard_is_off() -> None:
    normalized = TorumV1Params.normalize("XAUUSD", {})

    assert normalized.one_position_per_symbol is False
    assert normalized.third_entry_spacing_enabled is True
    assert normalized.third_entry_min_distance_pct == 0.20


def test_third_entry_spacing_blocks_close_third_entry_and_allows_lower_price() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        3900.0,
        4100.0,
    )
    open_positions = [
        SimpleNamespace(open_price=4055.31, order_id=201, opened_at=_madrid(1, 8, 30)),
        SimpleNamespace(open_price=4051.50, order_id=202, opened_at=_madrid(1, 8, 45)),
    ]
    params = {
        "pullback_entry_min_pct": 0.20,
        "pullback_entry_recovery_pct": 0.0,
        "pullback_lookback_bars": 12,
        "one_position_per_symbol": False,
        "third_entry_spacing_enabled": True,
        "third_entry_min_distance_pct": 0.20,
        # Historical rungs are intentionally irrelevant to the live guard.
        "executed_entry_price_ladder": [
            {"order_id": 100, "executed_price": 4200.0},
        ],
    }

    too_close = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=_madrid(1, 9, 21),
        current_price=4050.0,
        open_positions=open_positions,
    )
    assert too_close.should_buy is False
    assert too_close.reason == "third_entry_price_too_close"
    assert too_close.metadata is not None
    assert too_close.metadata["third_entry_open_position_count"] == 2
    assert too_close.metadata["third_entry_existing_pair_close"] is True
    assert too_close.metadata["third_entry_spacing_allowed"] is False

    sufficiently_lower = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=_madrid(1, 9, 21),
        current_price=4043.0,
        open_positions=open_positions,
    )
    assert sufficiently_lower.should_buy is True
    assert sufficiently_lower.metadata is not None
    assert sufficiently_lower.metadata["third_entry_spacing_allowed"] is True


def test_third_entry_spacing_releases_immediately_when_one_position_closes() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone", "rectangle",
        int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()),
        3900.0, 4100.0,
    )
    params = {
        "pullback_entry_min_pct": 0.20,
        "pullback_entry_recovery_pct": 0.0,
        "pullback_lookback_bars": 12,
        "third_entry_spacing_enabled": True,
        "third_entry_min_distance_pct": 0.20,
        "executed_entry_price_ladder": [
            {"order_id": 201, "executed_price": 4055.31},
            {"order_id": 202, "executed_price": 4051.50},
        ],
    }

    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params=params,
        now=_madrid(1, 9, 21),
        current_price=4050.0,
        # Order 202 already hit TP, so only the still-open position is supplied.
        open_positions=[SimpleNamespace(open_price=4055.31, order_id=201)],
    )

    assert decision.should_buy is True
    assert decision.metadata is not None
    assert decision.metadata["third_entry_open_position_count"] == 1
    assert decision.metadata["third_entry_spacing_applied"] is False


def test_third_entry_spacing_does_not_block_when_two_open_entries_are_far_apart() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone", "rectangle",
        int(_madrid(1, 9).timestamp()), int(_madrid(1, 10).timestamp()),
        3900.0, 4100.0,
    )
    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.20,
            "pullback_entry_recovery_pct": 0.0,
            "pullback_lookback_bars": 12,
            "third_entry_spacing_enabled": True,
            "third_entry_min_distance_pct": 0.20,
        },
        now=_madrid(1, 9, 21),
        current_price=4034.0,
        open_positions=[
            SimpleNamespace(open_price=4055.31, order_id=201),
            SimpleNamespace(open_price=4038.50, order_id=202),
        ],
    )

    assert decision.should_buy is True
    assert decision.metadata is not None
    assert decision.metadata["third_entry_existing_pair_close"] is False
    assert decision.metadata["third_entry_spacing_applied"] is False


def test_third_entry_spacing_ignores_finished_campaign() -> None:
    candles = [
        _m5_candle(_madrid(1, 9), 4048.0, 4050.0, 4047.0, 4049.0),
        _m5_candle(_madrid(1, 9, 5), 4049.0, 4049.0, 4034.0, 4036.0),
        _m5_candle(_madrid(1, 9, 10), 4036.0, 4037.0, 4032.0, 4033.0),
        _m5_candle(_madrid(1, 9, 15), 4031.0, 4036.0, 4028.0, 4034.0),
    ]
    zone = TorumV1OperationZone(
        "operation-zone",
        "rectangle",
        int(_madrid(1, 9).timestamp()),
        int(_madrid(1, 10).timestamp()),
        3900.0,
        4100.0,
    )
    decision = should_buy_torum_v1(
        symbol="XAUUSD",
        candles_m5=candles,
        operation_zones=[zone],
        params={
            "pullback_entry_min_pct": 0.20,
            "pullback_entry_recovery_pct": 0.0,
            "pullback_lookback_bars": 12,
            "one_position_per_symbol": False,
            "third_entry_spacing_enabled": True,
            "third_entry_min_distance_pct": 0.20,
            "executed_entry_price_ladder": [
                {"order_id": 301, "executed_price": 4055.31},
                {"order_id": 302, "executed_price": 4038.50},
            ],
        },
        now=_madrid(1, 9, 21),
        current_price=4034.0,
        open_positions=[],
    )

    assert decision.should_buy is True
    assert decision.metadata is not None
    assert decision.metadata["third_entry_spacing_applied"] is False


def test_runner_records_entry_price_ladder_across_open_campaign() -> None:
    db = _session()
    config = _config(db, "XAUUSD")
    first_confirmation = int(_madrid(1, 9).timestamp())
    second_confirmation = int(_madrid(1, 9, 15).timestamp())
    config.params_json = {
        "executed_entry_price_ladder": [
            {
                "order_id": 401,
                "confirmation_candle_time": first_confirmation,
                "executed_price": 4255.31,
            }
        ]
    }
    signal = StrategySignal(
        strategy_config_id=config.id,
        strategy_key="torum_v1",
        user_id=1,
        internal_symbol="XAUUSD",
        timeframe="M5",
        signal_type="ENTRY",
        side="BUY",
        entry_type="MARKET",
        confidence=0.72,
        reason="buy_pullback_confirmed_inside_zone",
        metadata_json={"confirmation_candle_time": second_confirmation},
        status="ORDER_EXECUTED",
    )
    prior = SimpleNamespace(
        open_price=4255.31,
        order_id=401,
        opened_at=_madrid(1, 9),
    )

    _record_torum_v1_executed_entry_cycle(
        config,
        signal,
        order_id=402,
        executed_price=4238.50,
        prior_open_positions=[prior],
    )

    ladder = config.params_json["executed_entry_price_ladder"]
    assert [entry["order_id"] for entry in ladder] == [401, 402]
    assert [entry["executed_price"] for entry in ladder] == [4255.31, 4238.50]


def test_auto_runner_failed_result_keeps_durable_retry_armed() -> None:
    from app.strategies.auto_runner import _raise_if_incomplete_result
    import pytest

    failed = SimpleNamespace(run=SimpleNamespace(status="FAILED"), message="symbol_lock_timeout")
    with pytest.raises(RuntimeError, match="torum_strategy_run_failed:42:symbol_lock_timeout"):
        _raise_if_incomplete_result(42, failed)


def test_auto_runner_terminal_result_does_not_retry_completed_decision() -> None:
    from app.strategies.auto_runner import _raise_if_incomplete_result

    for result in (
        SimpleNamespace(run=SimpleNamespace(status="FINISHED"), message="No setup"),
        SimpleNamespace(run=SimpleNamespace(status="FINISHED"), message="MT5 response is reconciling"),
    ):
        _raise_if_incomplete_result(42, result)

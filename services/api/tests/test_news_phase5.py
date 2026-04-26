from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.news.models import NewsEvent
from app.news.normalizer import normalize_country, normalize_currency, normalize_impact
from app.news.schemas import NewsJsonImportRequest, NewsSettingsUpdate
from app.news.service import NewsService, get_global_news_settings
from app.no_trade_zones.models import NoTradeZone
from app.no_trade_zones.service import NoTradeZoneService
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
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
    for symbol in ("XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY"):
        db.add(
            SymbolMapping(
                internal_symbol=symbol,
                broker_symbol=symbol,
                display_name=symbol,
                enabled=True,
                digits=2,
                point=0.01,
                contract_size=100.0,
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
    db.add(
        Tick(
            id=1,
            time=datetime.now(UTC),
            internal_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            bid=2325.0,
            ask=2325.2,
            last=None,
            volume=0.0,
            source="TEST",
        )
    )
    db.commit()
    return db


def _news_payload(event_time: datetime) -> NewsJsonImportRequest:
    return NewsJsonImportRequest(
        source="manual",
        events=[
            {
                "country": "USA",
                "currency": "usd",
                "impact": "high",
                "title": "Nonfarm Payrolls",
                "event_time": event_time.isoformat(),
                "previous_value": "150K",
                "forecast_value": "180K",
                "actual_value": None,
            }
        ],
    )


def test_news_normalization() -> None:
    assert normalize_impact("High") == "HIGH"
    assert normalize_currency("usd") == "USD"
    assert normalize_country("USA") == "United States"


def test_import_json_generates_default_usd_high_zones() -> None:
    db = _session()

    response = NewsService(db).import_json(_news_payload(datetime.now(UTC) + timedelta(hours=1)))

    assert response.saved == 1
    assert response.zones_generated == 4
    assert db.query(NewsEvent).count() == 1
    assert db.query(NoTradeZone).count() == 4


def test_regenerate_zones_uses_new_minutes() -> None:
    db = _session()
    event_time = datetime.now(UTC) + timedelta(hours=2)
    NewsService(db).import_json(_news_payload(event_time))

    settings, regenerated = NewsService(db).update_settings(NewsSettingsUpdate(minutes_before=30, minutes_after=90))

    zone = db.query(NoTradeZone).filter(NoTradeZone.internal_symbol == "XAUUSD").one()
    assert regenerated == 4
    assert settings.minutes_before == 30
    assert abs((zone.start_time.replace(tzinfo=UTC) - (event_time - timedelta(minutes=30))).total_seconds()) < 1
    assert abs((zone.end_time.replace(tzinfo=UTC) - (event_time + timedelta(minutes=90))).total_seconds()) < 1


def test_active_zone_check() -> None:
    db = _session()
    NewsService(db).update_settings(NewsSettingsUpdate(block_trading_during_news=True))
    NewsService(db).import_json(_news_payload(datetime.now(UTC)))

    blocked, zones = NoTradeZoneService(db).is_trading_blocked("XAUUSD", datetime.now(UTC))

    assert blocked is True
    assert len(zones) == 1


def test_risk_manager_blocks_when_news_block_enabled() -> None:
    db = _session()
    NewsService(db).update_settings(NewsSettingsUpdate(block_trading_during_news=True))
    NewsService(db).import_json(_news_payload(datetime.now(UTC)))
    trading_settings = db.query(TradingSettings).one()
    symbol_mapping = db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one()

    decision = RiskManager(db).evaluate(
        order=ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01),
        trading_settings=trading_settings,
        symbol_mapping=symbol_mapping,
        mt5_status=SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN"),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is False
    assert "Trading blocked by high-impact news zone" in "; ".join(decision.reasons)


def test_risk_manager_warns_when_news_block_disabled() -> None:
    db = _session()
    get_global_news_settings(db)
    NewsService(db).import_json(_news_payload(datetime.now(UTC)))
    trading_settings = db.query(TradingSettings).one()
    symbol_mapping = db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == "XAUUSD").one()

    decision = RiskManager(db).evaluate(
        order=ManualOrderRequest(internal_symbol="XAUUSD", side="BUY", volume=0.01),
        trading_settings=trading_settings,
        symbol_mapping=symbol_mapping,
        mt5_status=SimpleNamespace(connected_to_mt5=False, updated_at=None, account_trade_mode="UNKNOWN"),
        price_stale_after_seconds=120,
    )

    assert decision.allowed is True
    assert "High-impact news zone active" in "; ".join(decision.warnings)

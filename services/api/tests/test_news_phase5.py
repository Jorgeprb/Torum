from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.news.models import NewsEvent
from app.news.normalizer import normalize_country, normalize_currency, normalize_impact
from app.news.providers.finnhub_provider import is_high_impact, is_us_event, normalize_event
from app.news.schemas import NewsEventCreate, NewsJsonImportRequest, NewsSettingsUpdate
from app.news.service import NewsService, get_global_news_settings
from app.no_trade_zones.models import NoTradeZone
from app.no_trade_zones.service import NoTradeZoneService
from app.orders.models import Order  # noqa: F401
from app.risk.manager import RiskManager
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest
from app.positions.models import Position
from app.positions.service import PositionService
from app.users.models import User  # noqa: F401


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


def test_news_deduplicates_by_source_external_id_and_fingerprint() -> None:
    db = _session()
    service = NewsService(db)
    event_time = datetime.now(UTC) + timedelta(hours=1)

    first = NewsEventCreate(
        source="FINNHUB",
        external_id="abc",
        country="United States",
        currency="USD",
        impact="HIGH",
        title="Fed Interest Rate Decision",
        event_time=event_time,
    )
    second = first.model_copy(update={"forecast_value": "4.50"})
    no_external = first.model_copy(update={"external_id": None, "title": "Nonfarm Payrolls"})

    service.create_event(first)
    service.create_event(second)
    service.create_event(no_external)
    service.create_event(no_external)

    assert db.query(NewsEvent).count() == 2


def test_finnhub_filter_and_normalizer_match_us_high_logic() -> None:
    high_event = {
        "country": "US",
        "event": "Nonfarm Payrolls",
        "time": "2026-05-01T12:30:00",
        "prev": "150K",
        "estimate": "180K",
    }
    low_event = {
        "country": "US",
        "event": "Building Permits",
        "time": "2026-05-01T12:30:00",
    }
    non_us_event = {
        "country": "DE",
        "event": "CPI",
        "time": "2026-05-01T12:30:00",
    }
    normalized = normalize_event(high_event)

    assert is_us_event(high_event) is True
    assert is_high_impact(high_event) is True
    assert is_high_impact(low_event) is False
    assert is_us_event(non_us_event) is False
    assert normalized is not None
    assert normalized["source"] == "FINNHUB"
    assert normalized["country"] == "United States"
    assert normalized["currency"] == "USD"
    assert normalized["impact"] == "HIGH"


def test_finnhub_filter_keeps_usd_currency_event() -> None:
    event = {
        "currency": "USD",
        "event": "Fed Interest Rate Decision",
        "time": "2026-05-01T12:30:00",
    }

    assert is_us_event(event) is True
    assert is_high_impact(event) is True


def test_finnhub_normalizer_handles_common_shape() -> None:
    normalized = normalize_event(
        {
            "id": 151931297394,
            "time": "2026-05-01T12:30:00Z",
            "event": "Nonfarm Payrolls",
            "country": "US",
            "prev": 150,
            "estimate": 180.5,
            "actual": -0.3,
        }
    )

    assert normalized is not None
    assert normalized["source"] == "FINNHUB"
    assert normalized["external_id"] == "151931297394"
    assert normalized["country"] == "United States"
    assert normalized["currency"] == "USD"
    assert normalized["impact"] == "HIGH"
    assert normalized["previous_value"] == "150"
    assert normalized["forecast_value"] == "180.5"
    assert normalized["actual_value"] == "-0.3"
    NewsEventCreate.model_validate(normalized)


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


class MockProvider:
    name = "FINNHUB"

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[dict[str, object]]:
        return [
            {
                "source": "FINNHUB",
                "external_id": "mock-1",
                "country": "United States",
                "currency": "USD",
                "impact": "HIGH",
                "title": "CPI",
                "event_time": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            },
            {
                "source": "FINNHUB",
                "external_id": "mock-2",
                "country": "Germany",
                "currency": "EUR",
                "impact": "HIGH",
                "title": "German CPI",
                "event_time": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            },
        ]

    def normalize(self, raw_event: dict[str, object]) -> NewsEventCreate:
        return NewsEventCreate.model_validate(raw_event)


def test_sync_provider_mock_filters_usd_high_and_generates_zones() -> None:
    db = _session()
    service = NewsService(db)
    settings = get_global_news_settings(db)

    response = service._import_from_provider(MockProvider().fetch_events(datetime.now(UTC), datetime.now(UTC)), MockProvider(), filter_settings=settings)

    assert response.received == 2
    assert response.saved == 1
    assert response.zones_generated == 4
    assert db.query(NewsEvent).count() == 1
    assert db.query(NoTradeZone).count() == 4


def test_manual_risk_manager_does_not_block_when_news_block_enabled() -> None:
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

    assert decision.allowed is True


def test_news_block_only_blocks_opening_and_allows_close() -> None:
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
    position = Position(
        user_id=1,
        order_id=None,
        internal_symbol="XAUUSD",
        broker_symbol="XAUUSD",
        mode="PAPER",
        account_login=None,
        account_server=None,
        side="BUY",
        volume=0.01,
        open_price=2325.0,
        current_price=2325.0,
        sl=None,
        tp=None,
        profit=0.0,
        status="OPEN",
        mt5_position_ticket=None,
        opened_at=datetime.now(UTC),
    )
    db.add(position)
    db.commit()

    ok, message, closed = PositionService(db).close_position(position.id)

    assert decision.allowed is True
    assert ok is True
    assert message == "Paper position closed"
    assert closed is not None
    assert closed.status == "CLOSED"


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
    assert "High-impact news zone active" not in "; ".join(decision.warnings)

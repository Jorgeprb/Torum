from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.news.models import NewsEvent
from app.news.schemas import NewsJsonImportRequest, NewsSettingsUpdate
from app.news.service import NewsService
from app.no_trade_zones.models import NoTradeZone
from app.orders.models import Order  # noqa: F401
from app.positions.models import Position  # noqa: F401
from app.settings.trading_settings import TradingSettings  # noqa: F401
from app.strategies.models import StrategyConfig  # noqa: F401
from app.symbols.models import SymbolMapping
from app.users.models import User  # noqa: F401


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for symbol in ("XAUUSD", "XAUEUR"):
        db.add(SymbolMapping(internal_symbol=symbol, broker_symbol=symbol, display_name=symbol, enabled=True, digits=2, point=0.01, contract_size=100.0))
    db.commit()
    return db


def test_per_impact_rule_controls_zone_and_revision() -> None:
    db = _session()
    service = NewsService(db)
    settings, _ = service.update_settings(
        NewsSettingsUpdate(
            impact_filter=["HIGH"],
            impact_rules_json={
                "HIGH": {"enabled": True, "minutes_before": 5, "minutes_after": 10, "action": "WARN"},
            },
        )
    )
    event_time = datetime.now(UTC) + timedelta(hours=1)
    response = service.import_json(
        NewsJsonImportRequest(
            source="manual",
            events=[{
                "country": "United States",
                "currency": "USD",
                "impact": "HIGH",
                "title": "Test event",
                "event_time": event_time.isoformat(),
            }],
        )
    )

    assert response.saved == 1
    assert settings.revision == 2
    zones = db.query(NoTradeZone).all()
    assert len(zones) == 2
    assert all(zone.blocks_trading is False and zone.visual_only is True for zone in zones)
    assert abs((zones[0].start_time.replace(tzinfo=UTC) - (event_time - timedelta(minutes=5))).total_seconds()) < 1
    assert abs((zones[0].end_time.replace(tzinfo=UTC) - (event_time + timedelta(minutes=10))).total_seconds()) < 1
    assert db.query(NewsEvent).count() == 1

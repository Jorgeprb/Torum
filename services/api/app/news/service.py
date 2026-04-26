from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.news.models import NewsEvent, NewsSettings
from app.news.normalizer import ensure_utc_datetime, normalize_country, normalize_currency, normalize_impact
from app.news.providers.csv_provider import CsvNewsProvider
from app.news.providers.json_provider import JsonNewsProvider
from app.news.repository import get_news_settings, list_news_events
from app.news.schemas import (
    NewsCsvImportRequest,
    NewsEventCreate,
    NewsEventUpdate,
    NewsImportResponse,
    NewsJsonImportRequest,
    NewsSettingsUpdate,
)
from app.no_trade_zones.service import NoTradeZoneService
from app.symbols.models import SymbolMapping

DEFAULT_CURRENCIES = ["USD"]
DEFAULT_COUNTRIES = ["US", "United States"]
DEFAULT_IMPACTS = ["HIGH"]
DEFAULT_AFFECTED_SYMBOLS = ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY"]


def get_global_news_settings(db: Session) -> NewsSettings:
    settings = get_news_settings(db)
    if settings is not None:
        return settings

    settings = NewsSettings(
        user_id=None,
        draw_news_zones_enabled=True,
        block_trading_during_news=False,
        minutes_before=60,
        minutes_after=60,
        currencies_filter=DEFAULT_CURRENCIES,
        countries_filter=DEFAULT_COUNTRIES,
        impact_filter=DEFAULT_IMPACTS,
        affected_symbols=DEFAULT_AFFECTED_SYMBOLS,
        provider_enabled=False,
        provider_name="manual_csv_json",
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def seed_global_news_settings() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        get_global_news_settings(db)


class NewsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        currency: str | None = None,
        impact: str | None = None,
        limit: int = 500,
    ) -> list[NewsEvent]:
        return list_news_events(
            self.db,
            start_time=ensure_utc_datetime(start_time) if start_time is not None else None,
            end_time=ensure_utc_datetime(end_time) if end_time is not None else None,
            currency=normalize_currency(currency) if currency else None,
            impact=normalize_impact(impact) if impact else None,
            limit=limit,
        )

    def create_event(self, payload: NewsEventCreate) -> tuple[NewsEvent, int]:
        existing = self._existing_by_external_id(payload)
        if existing is not None:
            return existing, 0

        event = NewsEvent(**payload.model_dump())
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        zones = NoTradeZoneService(self.db).generate_zones_for_event(event, get_global_news_settings(self.db))
        return event, len(zones)

    def update_event(self, event: NewsEvent, payload: NewsEventUpdate) -> tuple[NewsEvent, int]:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(event, field, value)
        self.db.commit()
        self.db.refresh(event)
        zones = NoTradeZoneService(self.db).generate_zones_for_event(event, get_global_news_settings(self.db))
        return event, len(zones)

    def delete_event(self, event: NewsEvent) -> None:
        self.db.delete(event)
        self.db.commit()

    def import_json(self, payload: NewsJsonImportRequest) -> NewsImportResponse:
        provider = JsonNewsProvider(payload.events, source=payload.source)
        return self._import_from_provider(provider.fetch_events(datetime.min, datetime.max), provider)

    def import_csv(self, payload: NewsCsvImportRequest) -> NewsImportResponse:
        provider = CsvNewsProvider(payload.csv_text, source=payload.source)
        return self._import_from_provider(provider.fetch_events(datetime.min, datetime.max), provider)

    def update_settings(self, payload: NewsSettingsUpdate) -> tuple[NewsSettings, int]:
        settings = get_global_news_settings(self.db)
        data = payload.model_dump(exclude_unset=True)
        if "affected_symbols" in data:
            self._validate_symbols(data["affected_symbols"])
        for field, value in data.items():
            setattr(settings, field, value)
        self.db.commit()
        self.db.refresh(settings)
        regenerated = NoTradeZoneService(self.db).regenerate_zones(settings)
        return settings, regenerated

    def regenerate_zones(self) -> int:
        return NoTradeZoneService(self.db).regenerate_zones(get_global_news_settings(self.db))

    def _import_from_provider(self, raw_events: list[dict[str, object]], provider: object) -> NewsImportResponse:
        saved = 0
        zones_generated = 0
        errors: list[str] = []
        for index, raw_event in enumerate(raw_events, start=1):
            try:
                normalized = provider.normalize(raw_event)  # type: ignore[attr-defined]
                event, zone_count = self.create_event(normalized)
                saved += 1 if event.id else 0
                zones_generated += zone_count
            except Exception as exc:
                self.db.rollback()
                errors.append(f"event {index}: {exc}")
        return NewsImportResponse(received=len(raw_events), saved=saved, zones_generated=zones_generated, errors=errors)

    def _existing_by_external_id(self, payload: NewsEventCreate) -> NewsEvent | None:
        if not payload.external_id:
            return None
        return self.db.scalar(
            select(NewsEvent).where(
                NewsEvent.source == payload.source,
                NewsEvent.external_id == payload.external_id,
            )
        )

    def _validate_symbols(self, symbols: list[str]) -> None:
        existing = set(self.db.scalars(select(SymbolMapping.internal_symbol)))
        missing = [symbol for symbol in symbols if symbol not in existing]
        if missing:
            raise ValueError(f"Unknown affected symbols: {', '.join(missing)}")


def normalize_settings_payload(payload: NewsSettingsUpdate) -> NewsSettingsUpdate:
    if payload.countries_filter is not None:
        payload.countries_filter = [normalize_country(country) for country in payload.countries_filter]
    return payload

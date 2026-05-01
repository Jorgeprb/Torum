from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.news.models import NewsEvent, NewsSettings
from app.news.normalizer import ensure_utc_datetime, normalize_country, normalize_currency, normalize_impact
from app.news.providers.csv_provider import CsvNewsProvider
from app.news.providers.finnhub_provider import FinnhubProvider
from app.news.providers.json_provider import JsonNewsProvider
from app.news.repository import get_news_settings, list_news_events
from app.news.schemas import (
    NewsCsvImportRequest,
    NewsEventCreate,
    NewsEventRead,
    NewsEventUpdate,
    NewsImportResponse,
    NewsJsonImportRequest,
    NewsProviderStatusRead,
    NewsProviderSyncResponse,
    NewsSettingsUpdate,
)
from app.no_trade_zones.service import NoTradeZoneService
from app.no_trade_zones.models import NoTradeZone
from app.symbols.models import SymbolMapping

DEFAULT_CURRENCIES = ["USD"]
DEFAULT_COUNTRIES = ["US", "United States"]
DEFAULT_IMPACTS = ["HIGH"]
DEFAULT_AFFECTED_SYMBOLS = ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY"]
DEFAULT_PROVIDER = "FINNHUB"
DEFAULT_SYNC_INTERVAL_MINUTES = 1440
DEFAULT_DAYS_AHEAD = 14


def get_global_news_settings(db: Session) -> NewsSettings:
    settings = get_news_settings(db)
    if settings is not None:
        if settings.provider.upper() not in {DEFAULT_PROVIDER, "MANUAL"}:
            settings.provider = DEFAULT_PROVIDER
            settings.provider_name = DEFAULT_PROVIDER
            settings.sync_interval_minutes = DEFAULT_SYNC_INTERVAL_MINUTES
            settings.days_ahead = max(settings.days_ahead, DEFAULT_DAYS_AHEAD)
            settings.provider_enabled = True
            settings.auto_sync_enabled = True
            db.commit()
            db.refresh(settings)
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
        provider_enabled=True,
        provider_name=DEFAULT_PROVIDER,
        provider=DEFAULT_PROVIDER,
        auto_sync_enabled=True,
        sync_interval_minutes=DEFAULT_SYNC_INTERVAL_MINUTES,
        days_ahead=DEFAULT_DAYS_AHEAD,
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
        existing = self._existing_event(payload)
        if existing is not None:
            return self.update_event(existing, NewsEventUpdate(**payload.model_dump()))

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
        if "provider" in data:
            data["provider_name"] = data["provider"]
        elif "provider_name" in data:
            provider = str(data["provider_name"]).strip().upper()
            if provider in {"FINNHUB", "MANUAL"}:
                data["provider"] = provider
        for field, value in data.items():
            setattr(settings, field, value)
        self.db.commit()
        self.db.refresh(settings)
        regenerated = NoTradeZoneService(self.db).regenerate_zones(settings)
        return settings, regenerated

    def regenerate_zones(self) -> int:
        return NoTradeZoneService(self.db).regenerate_zones(get_global_news_settings(self.db))

    def provider_status(self) -> NewsProviderStatusRead:
        settings = get_global_news_settings(self.db)
        next_event = self.db.scalar(
            select(NewsEvent)
            .where(
                NewsEvent.event_time >= datetime.now(UTC),
                NewsEvent.currency.in_(settings.currencies_filter),
                NewsEvent.country.in_(settings.countries_filter),
                NewsEvent.impact.in_(settings.impact_filter),
            )
            .order_by(NewsEvent.event_time)
            .limit(1)
        )
        imported_events = self.db.scalar(select(func.count(NewsEvent.id))) or 0
        generated_zones = self.db.scalar(select(func.count(NoTradeZone.id)).where(NoTradeZone.news_event_id.is_not(None))) or 0
        return NewsProviderStatusRead(
            provider=settings.provider,
            provider_enabled=settings.provider_enabled,
            auto_sync_enabled=settings.auto_sync_enabled,
            sync_interval_minutes=settings.sync_interval_minutes,
            days_ahead=settings.days_ahead,
            block_trading_during_news=settings.block_trading_during_news,
            draw_news_zones_enabled=settings.draw_news_zones_enabled,
            minutes_before=settings.minutes_before,
            minutes_after=settings.minutes_after,
            last_sync_at=settings.last_sync_at,
            last_sync_status=settings.last_sync_status,
            last_sync_error=settings.last_sync_error,
            next_event=NewsEventRead.model_validate(next_event) if next_event is not None else None,
            imported_events=imported_events,
            generated_zones=generated_zones,
        )

    def sync_provider(self) -> NewsProviderSyncResponse:
        settings = get_global_news_settings(self.db)
        started_at = datetime.now(UTC)
        provider_name = settings.provider.upper()
        if provider_name == "MANUAL":
            return self._mark_sync_result(
                settings,
                provider_name,
                started_at,
                received=0,
                saved=0,
                zones_generated=0,
                errors=["Provider MANUAL does not sync automatically"],
            )

        try:
            provider = self._build_provider(settings)
            end = started_at + timedelta(days=settings.days_ahead)
            response = self._import_from_provider(provider.fetch_events(started_at, end), provider, filter_settings=settings)
            return self._mark_sync_result(
                settings,
                provider_name,
                started_at,
                received=response.received,
                saved=response.saved,
                zones_generated=response.zones_generated,
                errors=response.errors,
            )
        except Exception as exc:
            self.db.rollback()
            return self._mark_sync_result(
                settings,
                provider_name,
                started_at,
                received=0,
                saved=0,
                zones_generated=0,
                errors=[str(exc)],
            )

    def _import_from_provider(
        self,
        raw_events: list[dict[str, object]],
        provider: object,
        filter_settings: NewsSettings | None = None,
    ) -> NewsImportResponse:
        saved = 0
        zones_generated = 0
        errors: list[str] = []
        for index, raw_event in enumerate(raw_events, start=1):
            try:
                normalized = provider.normalize(raw_event)  # type: ignore[attr-defined]
                if filter_settings is not None and not _event_payload_matches_settings(normalized, filter_settings):
                    continue
                _event, zone_count = self.create_event(normalized)
                saved += 1
                zones_generated += zone_count
            except Exception as exc:
                self.db.rollback()
                errors.append(f"event {index}: {exc}")
        return NewsImportResponse(received=len(raw_events), saved=saved, zones_generated=zones_generated, errors=errors)

    def _existing_event(self, payload: NewsEventCreate) -> NewsEvent | None:
        if payload.external_id:
            existing = self.db.scalar(
                select(NewsEvent).where(
                    NewsEvent.source == payload.source,
                    NewsEvent.external_id == payload.external_id,
                )
            )
            if existing is not None:
                return existing
        return self.db.scalar(
            select(NewsEvent).where(
                NewsEvent.source == payload.source,
                NewsEvent.currency == payload.currency,
                NewsEvent.title == payload.title,
                NewsEvent.event_time == payload.event_time,
            )
        )

    def _build_provider(self, settings: NewsSettings) -> object:
        app_settings = get_settings()
        provider = settings.provider.upper()
        if provider == "FINNHUB":
            return FinnhubProvider(
                api_key=app_settings.finnhub_api_key.get_secret_value() if app_settings.finnhub_api_key else None,
                url=app_settings.finnhub_calendar_url,
                timeout_seconds=app_settings.news_provider_timeout_seconds,
            )
        raise ValueError(f"Unsupported provider: {settings.provider}")

    def _mark_sync_result(
        self,
        settings: NewsSettings,
        provider: str,
        started_at: datetime,
        *,
        received: int,
        saved: int,
        zones_generated: int,
        errors: list[str],
    ) -> NewsProviderSyncResponse:
        finished_at = datetime.now(UTC)
        settings.last_sync_at = finished_at
        settings.last_sync_status = "ERROR" if errors else "OK"
        settings.last_sync_error = "; ".join(errors) if errors else None
        self.db.commit()
        return NewsProviderSyncResponse(
            provider=provider,
            started_at=started_at,
            finished_at=finished_at,
            status=settings.last_sync_status or "ERROR",
            received=received,
            saved=saved,
            zones_generated=zones_generated,
            errors=errors,
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


def _event_payload_matches_settings(payload: NewsEventCreate, settings: NewsSettings) -> bool:
    countries = {normalize_country(value) for value in settings.countries_filter}
    return (
        payload.currency.upper() in {value.upper() for value in settings.currencies_filter}
        and payload.impact.upper() in {value.upper() for value in settings.impact_filter}
        and normalize_country(payload.country) in countries
    )

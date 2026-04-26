from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.news.models import NewsEvent, NewsSettings
from app.no_trade_zones.models import NoTradeZone
from app.no_trade_zones.repository import list_zones
from app.no_trade_zones.schemas import NoTradeZoneCreate, NoTradeZoneUpdate


class NoTradeZoneService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_zones_for_event(self, event: NewsEvent, settings: NewsSettings) -> list[NoTradeZone]:
        self.db.execute(delete(NoTradeZone).where(NoTradeZone.news_event_id == event.id))
        if not event_matches_settings(event, settings):
            self.db.commit()
            return []

        start_time = _as_utc(event.event_time) - timedelta(minutes=settings.minutes_before)
        end_time = _as_utc(event.event_time) + timedelta(minutes=settings.minutes_after)
        zones: list[NoTradeZone] = []
        for symbol in settings.affected_symbols:
            zone = NoTradeZone(
                news_event_id=event.id,
                source=event.source,
                reason=f"{event.impact} {event.currency} news: {event.title}",
                internal_symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                enabled=True,
                blocks_trading=settings.block_trading_during_news,
                visual_only=not settings.block_trading_during_news,
            )
            self.db.add(zone)
            zones.append(zone)
        self.db.commit()
        for zone in zones:
            self.db.refresh(zone)
        return zones

    def regenerate_zones(self, settings: NewsSettings) -> int:
        self.db.execute(delete(NoTradeZone).where(NoTradeZone.news_event_id.is_not(None)))
        events = self.db.scalars(select(NewsEvent).order_by(NewsEvent.event_time)).all()
        count = 0
        for event in events:
            if not event_matches_settings(event, settings):
                continue
            start_time = _as_utc(event.event_time) - timedelta(minutes=settings.minutes_before)
            end_time = _as_utc(event.event_time) + timedelta(minutes=settings.minutes_after)
            for symbol in settings.affected_symbols:
                self.db.add(
                    NoTradeZone(
                        news_event_id=event.id,
                        source=event.source,
                        reason=f"{event.impact} {event.currency} news: {event.title}",
                        internal_symbol=symbol,
                        start_time=start_time,
                        end_time=end_time,
                        enabled=True,
                        blocks_trading=settings.block_trading_during_news,
                        visual_only=not settings.block_trading_during_news,
                    )
                )
                count += 1
        self.db.commit()
        return count

    def create_zone(self, payload: NoTradeZoneCreate) -> NoTradeZone:
        zone = NoTradeZone(**payload.model_dump())
        self.db.add(zone)
        self.db.commit()
        self.db.refresh(zone)
        return zone

    def update_zone(self, zone: NoTradeZone, payload: NoTradeZoneUpdate) -> NoTradeZone:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(zone, field, value)
        if zone.end_time <= zone.start_time:
            raise ValueError("end_time must be after start_time")
        self.db.commit()
        self.db.refresh(zone)
        return zone

    def delete_zone(self, zone: NoTradeZone) -> None:
        self.db.delete(zone)
        self.db.commit()

    def list_zones(
        self,
        symbol: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        include_disabled: bool = False,
    ) -> list[NoTradeZone]:
        return list_zones(self.db, symbol=symbol, start_time=start_time, end_time=end_time, include_disabled=include_disabled)

    def get_active_zones(self, symbol: str, at_time: datetime | None = None) -> list[NoTradeZone]:
        checked_at = _as_utc(at_time or datetime.now(UTC))
        return list(
            self.db.scalars(
                select(NoTradeZone)
                .where(
                    NoTradeZone.internal_symbol == symbol.upper(),
                    NoTradeZone.enabled.is_(True),
                    NoTradeZone.start_time <= checked_at,
                    NoTradeZone.end_time >= checked_at,
                )
                .order_by(NoTradeZone.start_time)
            )
        )

    def is_trading_blocked(self, symbol: str, at_time: datetime | None = None) -> tuple[bool, list[NoTradeZone]]:
        active_zones = self.get_active_zones(symbol, at_time)
        blocking_zones = [zone for zone in active_zones if zone.blocks_trading]
        return bool(blocking_zones), blocking_zones


def event_matches_settings(event: NewsEvent, settings: NewsSettings) -> bool:
    return (
        event.currency.upper() in {value.upper() for value in settings.currencies_filter}
        and event.impact.upper() in {value.upper() for value in settings.impact_filter}
        and event.country in set(settings.countries_filter)
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

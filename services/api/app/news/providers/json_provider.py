from datetime import datetime

from app.news.normalizer import normalize_raw_event
from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.schemas import NewsEventCreate


class JsonNewsProvider(BaseNewsProvider):
    name = "manual_json"

    def __init__(self, events: list[RawNewsEvent], source: str = "manual_json") -> None:
        self.events = events
        self.source = source

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        return self.events

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        return NewsEventCreate.model_validate(normalize_raw_event(raw_event, default_source=self.source))

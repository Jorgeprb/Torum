from datetime import datetime

from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.schemas import NewsEventCreate


class FutureApiNewsProvider(BaseNewsProvider):
    name = "future_api"

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        raise NotImplementedError("Configure a licensed economic-calendar API before enabling this provider.")

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        raise NotImplementedError("Future API normalization belongs next to the selected provider contract.")

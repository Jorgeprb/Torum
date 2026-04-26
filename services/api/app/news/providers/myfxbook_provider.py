from datetime import datetime

from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.schemas import NewsEventCreate


class MyfxbookProvider(BaseNewsProvider):
    name = "myfxbook"

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        raise NotImplementedError(
            "Myfxbook calendar integration requires an authorized, stable API contract. "
            "Torum does not scrape Myfxbook pages as a required data source."
        )

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        raise NotImplementedError("Myfxbook normalization will be implemented when an authorized feed is configured.")

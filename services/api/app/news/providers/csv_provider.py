import csv
from datetime import datetime
from io import StringIO

from app.news.normalizer import normalize_raw_event
from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.schemas import NewsEventCreate


class CsvNewsProvider(BaseNewsProvider):
    name = "manual_csv"

    def __init__(self, csv_text: str, source: str = "manual_csv") -> None:
        self.csv_text = csv_text
        self.source = source

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        reader = csv.DictReader(StringIO(self.csv_text))
        return [dict(row) for row in reader]

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        if not raw_event.get("source"):
            raw_event = {**raw_event, "source": self.source}
        return NewsEventCreate.model_validate(normalize_raw_event(raw_event, default_source=self.source))

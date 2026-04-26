from datetime import datetime

from sqlalchemy.orm import Session

from app.news.providers.base import BaseNewsProvider
from app.news.service import NewsService


class NewsScheduler:
    def __init__(self, db: Session, provider: BaseNewsProvider) -> None:
        self.db = db
        self.provider = provider

    def run_once(self, start_date: datetime, end_date: datetime) -> int:
        raw_events = self.provider.fetch_events(start_date, end_date)
        service = NewsService(self.db)
        saved = 0
        for raw_event in raw_events:
            service.create_event(self.provider.normalize(raw_event))
            saved += 1
        return saved

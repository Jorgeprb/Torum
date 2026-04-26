from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.news.schemas import NewsEventCreate

RawNewsEvent = dict[str, Any]


class BaseNewsProvider(ABC):
    name: str

    @abstractmethod
    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        raise NotImplementedError

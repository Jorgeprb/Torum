from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

from app.news.impact_classifier import classify_impact
from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.schemas import NewsEventCreate

FMP_ECONOMIC_CALENDAR_URL = "https://financialmodelingprep.com/stable/economic-calendar"


class FmpEconomicCalendarProvider(BaseNewsProvider):
    name = "FMP"

    def __init__(
        self,
        *,
        api_key: str,
        url: str = FMP_ECONOMIC_CALENDAR_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.url = url
        self.timeout_seconds = timeout_seconds

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        if not self.api_key:
            return []
        response = requests.get(
            self.url,
            params={
                "from": _as_date(start_date),
                "to": _as_date(end_date),
                "apikey": self.api_key,
            },
            timeout=self.timeout_seconds,
            headers={"User-Agent": "Torum/1.0 economic-calendar"},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            for key in ("economicCalendar", "data", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise RuntimeError("Respuesta inesperada del calendario económico de FMP")
        return [item for item in data if isinstance(item, dict)]

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        title = _first(raw_event, "event", "title", "name", "indicator")
        event_time = _parse_utc(_first(raw_event, "date", "datetime", "time", "event_time"))
        country = str(_first(raw_event, "country", "countryName") or "United States")
        currency = str(_first(raw_event, "currency") or ("USD" if country.upper() in {"US", "USA", "UNITED STATES"} else ""))
        if not title or not currency:
            raise ValueError("Evento FMP sin título/divisa")
        return NewsEventCreate(
            source="FMP",
            external_id=_optional(_first(raw_event, "id", "eventId", "event_id")),
            country=country,
            currency=currency,
            impact=classify_impact(str(title), _first(raw_event, "impact", "importance")),
            title=str(title),
            event_time=event_time,
            previous_value=_optional(_first(raw_event, "previous", "prev")),
            forecast_value=_optional(_first(raw_event, "estimate", "forecast", "consensus")),
            actual_value=_optional(_first(raw_event, "actual")),
            url=_optional(_first(raw_event, "url", "link")),
            raw_payload_json=dict(raw_event),
        )


def _as_date(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%d")


def _parse_utc(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Evento FMP sin fecha/hora")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        raise ValueError(f"Fecha FMP no reconocida: {raw}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _first(event: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if event.get(key) not in (None, ""):
            return event[key]
    return None


def _optional(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

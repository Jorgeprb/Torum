import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests


FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"
SPAIN_TZ = ZoneInfo("Europe/Madrid")


NOT_HIGH_PATTERNS = [
    r"\bbuilding permits\b",
    r"\bhousing starts\b",
    r"\bnew home sales\b",
    r"\bexisting home sales\b",
    r"\bpending home sales\b",
    r"\bs&p global .*pmi final\b",
    r"\bmarkit .*pmi final\b",
    r"\bmanufacturing pmi final\b",
    r"\bservices pmi final\b",
    r"\bcomposite pmi final\b",
]


HIGH_IMPACT_PATTERNS = [
    r"\bnon[-\s]?farm payrolls?\b",
    r"\bnfp\b",
    r"\bnonfarm employment\b",
    r"\bnon-farm employment\b",
    r"\bunemployment rate\b",
    r"\binitial jobless claims\b",
    r"\bcontinuing jobless claims\b",
    r"\bcpi\b",
    r"\bcore cpi\b",
    r"\bconsumer price index\b",
    r"\bppi\b",
    r"\bcore ppi\b",
    r"\bproducer price index\b",
    r"\bpce price index\b",
    r"\bcore pce\b",
    r"\bpersonal consumption expenditures\b",
    r"\bfed interest rate decision\b",
    r"\bfederal funds rate\b",
    r"\binterest rate decision\b",
    r"\brate decision\b",
    r"\bfomc\b",
    r"\bfomc statement\b",
    r"\bfomc minutes\b",
    r"\bfed press conference\b",
    r"\bfed chair\b",
    r"\bpowell\b",
    r"\bgdp\b",
    r"\bgross domestic product\b",
    r"\bretail sales\b",
    r"\bcore retail sales\b",
    r"\bism manufacturing\b",
    r"\bism services\b",
    r"\bism non[-\s]?manufacturing\b",
    r"\bjolts\b",
    r"\badp employment\b",
    r"\bdurable goods orders\b",
    r"\bconsumer confidence\b",
    r"\bmichigan consumer sentiment\b",
]


def current_week_range_spain() -> tuple[str, str]:
    today = datetime.now(SPAIN_TZ).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=14)
    return monday.isoformat(), sunday.isoformat()


def first_present(event: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = event.get(key)
        if value not in (None, ""):
            return value
    return None


def event_text(event: dict[str, Any]) -> str:
    fields = ["event", "title", "name", "indicator", "category"]
    return " ".join(str(event.get(field, "")) for field in fields).lower()


def matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def is_high_impact(event: dict[str, Any]) -> bool:
    text = event_text(event)

    if matches(text, NOT_HIGH_PATTERNS):
        return False

    return matches(text, HIGH_IMPACT_PATTERNS)


def is_us_event(event: dict[str, Any]) -> bool:
    country = str(event.get("country") or "").strip().lower()
    country_name = str(event.get("countryName") or "").strip().lower()
    region = str(event.get("region") or "").strip().lower()
    currency = str(event.get("currency") or "").strip().upper()

    us_values = {
        "us",
        "usa",
        "u.s.",
        "u.s.a.",
        "united states",
        "united states of america",
    }

    return (
        country in us_values
        or country_name in us_values
        or region in us_values
        or currency == "USD"
    )


def parse_datetime_to_spain(
    value: Any,
    input_tz: timezone | ZoneInfo = timezone.utc,
) -> str:
    raw = str(value).strip()

    if not raw:
        raise ValueError("Evento sin fecha/hora")

    parsed: datetime | None = None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(f"No se pudo parsear fecha: {raw}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=input_tz)

    return parsed.astimezone(SPAIN_TZ).isoformat()


def fetch_finnhub_events(
    start_date: str,
    end_date: str,
    api_key: str = FINNHUB_API_KEY,
) -> list[dict[str, Any]]:
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is required")

    response = requests.get(
        FINNHUB_URL,
        params={
            "from": start_date,
            "to": end_date,
            "token": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and isinstance(data.get("economicCalendar"), list):
        return data["economicCalendar"]

    raise RuntimeError(f"Respuesta inesperada de Finnhub: {data}")


def normalize_event(
    event: dict[str, Any],
    input_tz: timezone | ZoneInfo = timezone.utc,
) -> dict[str, Any] | None:
    title = first_present(event, ["event", "title", "name", "indicator", "category"])
    raw_time = first_present(event, ["time", "date", "datetime", "event_time"])

    if not title or not raw_time:
        return None

    try:
        event_time_es = parse_datetime_to_spain(raw_time, input_tz=input_tz)
    except ValueError:
        return None

    return {
        "source": "FINNHUB",
        "country": "United States",
        "currency": "USD",
        "impact": "HIGH",
        "title": title,
        "event_time": event_time_es,
        "previous_value": first_present(event, ["prev", "previous"]),
        "forecast_value": first_present(event, ["forecast", "estimate", "consensus"]),
        "actual_value": first_present(event, ["actual"]),
    }


def dedupe_same_time(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_time: dict[str, dict[str, Any]] = {}

    for event in events:
        key = event["event_time"]
        if key not in by_time:
            by_time[key] = event

    return sorted(by_time.values(), key=lambda item: item["event_time"])


def get_finnhub_us_high_impact_news(
    start_date: str | None = None,
    end_date: str | None = None,
    input_tz: timezone | ZoneInfo = timezone.utc,
) -> list[dict[str, Any]]:
    """
    Devuelve noticias HIGH de EEUU/USD desde Finnhub en hora española.
    El campo event_time se guarda directamente en Europe/Madrid.
    Elimina duplicados si varias noticias caen exactamente a la misma hora.
    """
    if start_date is None or end_date is None:
        start_date, end_date = current_week_range_spain()

    raw_events = fetch_finnhub_events(start_date, end_date)

    news = [
        normalized
        for event in raw_events
        if is_us_event(event) and is_high_impact(event)
        if (normalized := normalize_event(event, input_tz=input_tz)) is not None
    ]

    return dedupe_same_time(news)


# Variable que puede recoger Torum directamente.
finnhub_news = get_finnhub_us_high_impact_news()
print(finnhub_news)
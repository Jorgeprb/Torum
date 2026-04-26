from datetime import UTC, datetime
from typing import Any

COUNTRY_ALIASES = {
    "US": "United States",
    "USA": "United States",
    "U.S.": "United States",
    "UNITED STATES": "United States",
    "UNITED STATES OF AMERICA": "United States",
}


def normalize_impact(value: str) -> str:
    normalized = value.strip().upper()
    aliases = {
        "HIGH IMPACT": "HIGH",
        "MED": "MEDIUM",
        "MID": "MEDIUM",
        "LOW IMPACT": "LOW",
    }
    return aliases.get(normalized, normalized)


def normalize_currency(value: str) -> str:
    return value.strip().upper()


def normalize_country(value: str) -> str:
    stripped = value.strip()
    return COUNTRY_ALIASES.get(stripped.upper(), stripped)


def ensure_utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    else:
        parsed = value
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_raw_event(raw_event: dict[str, Any], default_source: str = "manual") -> dict[str, Any]:
    source = str(raw_event.get("source") or default_source or "manual")
    event_time = raw_event.get("event_time") or raw_event.get("time")
    if event_time is None:
        raise ValueError("event_time is required")
    title = str(raw_event.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    return {
        "source": source,
        "external_id": _optional_str(raw_event.get("external_id")),
        "country": normalize_country(str(raw_event.get("country") or "")),
        "currency": normalize_currency(str(raw_event.get("currency") or "")),
        "impact": normalize_impact(str(raw_event.get("impact") or "")),
        "title": title,
        "event_time": ensure_utc_datetime(event_time),
        "previous_value": _optional_str(raw_event.get("previous_value") or raw_event.get("previous")),
        "forecast_value": _optional_str(raw_event.get("forecast_value") or raw_event.get("forecast")),
        "actual_value": _optional_str(raw_event.get("actual_value") or raw_event.get("actual")),
        "url": _optional_str(raw_event.get("url")),
        "raw_payload_json": raw_event,
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

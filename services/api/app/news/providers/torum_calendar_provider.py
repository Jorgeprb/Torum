from __future__ import annotations

import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from app.news.impact_classifier import canonical_event_family, classify_impact
from app.news.providers.base import BaseNewsProvider, RawNewsEvent
from app.news.providers.fmp_provider import FmpEconomicCalendarProvider
from app.news.schemas import NewsEventCreate

US_EASTERN = ZoneInfo("America/New_York")

DEFAULT_BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
DEFAULT_BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
DEFAULT_CENSUS_CALENDAR_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
DEFAULT_FED_CALENDAR_BASE_URL = "https://www.federalreserve.gov/newsevents"


@dataclass(frozen=True)
class SourceResult:
    name: str
    events: list[RawNewsEvent]
    error: str | None = None
    required: bool = True


class TorumCalendarProvider(BaseNewsProvider):
    """Resilient US macro calendar.

    BLS, BEA, Federal Reserve and Census are independent, no-key primary
    sources. FMP is an optional one-key enrichment layer. Failure of one source
    does not prevent the others from being used.
    """

    name = "TORUM"

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        bls_ics_url: str = DEFAULT_BLS_ICS_URL,
        bea_release_dates_url: str = DEFAULT_BEA_RELEASE_DATES_URL,
        census_calendar_url: str = DEFAULT_CENSUS_CALENDAR_URL,
        fed_calendar_base_url: str = DEFAULT_FED_CALENDAR_BASE_URL,
        fmp_api_key: str | None = None,
        fmp_url: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.bls_ics_url = bls_ics_url
        self.bea_release_dates_url = bea_release_dates_url
        self.census_calendar_url = census_calendar_url
        self.fed_calendar_base_url = fed_calendar_base_url.rstrip("/")
        self.fmp_api_key = str(fmp_api_key or "").strip()
        self.fmp_url = fmp_url
        self.warnings: list[str] = []
        self.successful_sources: list[str] = []
        self.failed_required_sources: list[str] = []
        self.safe_to_reconcile = False

    def fetch_events(self, start_date: datetime, end_date: datetime) -> list[RawNewsEvent]:
        start = _ensure_utc(start_date)
        end = _ensure_utc(end_date)
        self.warnings = []
        self.successful_sources = []
        self.failed_required_sources = []
        self.safe_to_reconcile = False
        results: list[SourceResult] = []
        loaders: dict[str, tuple[bool, Callable[[], list[RawNewsEvent]]]] = {
            "BLS": (True, lambda: self._fetch_bls(start, end)),
            "BEA": (True, lambda: self._fetch_bea(start, end)),
            "FED": (True, lambda: self._fetch_fed(start, end)),
            "CENSUS": (True, lambda: self._fetch_census(start, end)),
        }
        if self.fmp_api_key:
            def load_fmp() -> list[RawNewsEvent]:
                fmp = FmpEconomicCalendarProvider(
                    api_key=self.fmp_api_key,
                    url=self.fmp_url or "https://financialmodelingprep.com/stable/economic-calendar",
                    timeout_seconds=self.timeout_seconds,
                )
                return [fmp.normalize(item).model_dump(mode="json") for item in fmp.fetch_events(start, end)]
            loaders["FMP"] = (False, load_fmp)

        # Provider I/O must never serialize four independent internet requests.
        # Parallel fetch keeps a manual sync bounded roughly by the slowest source.
        with ThreadPoolExecutor(max_workers=len(loaders), thread_name_prefix="torum-news") as pool:
            futures = {pool.submit(loader): (name, required) for name, (required, loader) in loaders.items()}
            for future in as_completed(futures):
                name, required = futures[future]
                try:
                    events = future.result()
                    results.append(SourceResult(name=name, events=events, required=required))
                    self.successful_sources.append(name)
                except Exception as exc:  # one source failure must not erase the rest
                    prefix = name if required else f"{name} opcional"
                    message = f"{prefix}: {exc}"
                    results.append(SourceResult(name=name, events=[], error=message, required=required))
                    self.warnings.append(message)
                    if required:
                        self.failed_required_sources.append(name)

        if not any(name in self.successful_sources for name in {"BLS", "BEA", "FED", "CENSUS"}):
            raise RuntimeError("No se pudo consultar ninguna fuente oficial del calendario económico")
        self.safe_to_reconcile = not self.failed_required_sources
        flattened = [event for result in results for event in result.events]
        return merge_calendar_events(flattened, start, end)

    def normalize(self, raw_event: RawNewsEvent) -> NewsEventCreate:
        return NewsEventCreate.model_validate(raw_event)

    def _get_text(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "Torum/1.0 economic-calendar (contact: local-app)"},
        )
        response.raise_for_status()
        return response.text

    def _get_json(self, url: str) -> Any:
        response = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "Torum/1.0 economic-calendar (contact: local-app)"},
        )
        response.raise_for_status()
        return response.json()

    def _fetch_bls(self, start: datetime, end: datetime) -> list[RawNewsEvent]:
        body = self._get_text(self.bls_ics_url)
        wide_start = datetime(start.year, 1, 1, tzinfo=UTC)
        wide_end = datetime(end.year, 12, 31, 23, 59, tzinfo=UTC)
        parsed = parse_bls_ics(body, wide_start, wide_end)
        if "BEGIN:VEVENT" in body and not parsed:
            raise RuntimeError("el iCal se recibió pero no pudo interpretarse")
        return [item for item in parsed if start <= _parse_iso_utc(item["event_time"]) <= end]

    def _fetch_bea(self, start: datetime, end: datetime) -> list[RawNewsEvent]:
        data = self._get_json(self.bea_release_dates_url)
        wide_start = datetime(start.year, 1, 1, tzinfo=UTC)
        wide_end = datetime(end.year, 12, 31, 23, 59, tzinfo=UTC)
        parsed = parse_bea_release_dates(data, wide_start, wide_end)
        has_release_dates = isinstance(data, dict) and any(
            isinstance(value, dict) and isinstance(value.get("release_dates"), list)
            for value in data.values()
        )
        if has_release_dates and not parsed:
            raise RuntimeError("el JSON se recibió pero no pudo interpretarse")
        return [item for item in parsed if start <= _parse_iso_utc(item["event_time"]) <= end]

    def _fetch_census(self, start: datetime, end: datetime) -> list[RawNewsEvent]:
        body = self._get_text(self.census_calendar_url)
        wide_start = datetime(start.year, 1, 1, tzinfo=UTC)
        wide_end = datetime(end.year, 12, 31, 23, 59, tzinfo=UTC)
        parsed = parse_census_calendar(body, wide_start, wide_end)
        if "Economic Indicator" in body and not parsed:
            raise RuntimeError("la tabla se recibió pero no pudo interpretarse")
        return [item for item in parsed if start <= _parse_iso_utc(item["event_time"]) <= end]

    def _fetch_fed(self, start: datetime, end: datetime) -> list[RawNewsEvent]:
        pages: list[tuple[int, int, str]] = []
        cursor = date(start.year, start.month, 1)
        final_month = date(end.year, end.month, 1)
        while cursor <= final_month:
            month_name = cursor.strftime("%B").lower()
            candidate_urls = [
                f"{self.fed_calendar_base_url}/{cursor.year}-{month_name}.htm",
                f"{self.fed_calendar_base_url}/{cursor.year}-{cursor.month:02d}.htm",
            ]
            body: str | None = None
            last_error: Exception | None = None
            for url in candidate_urls:
                try:
                    body = self._get_text(url)
                    break
                except Exception as exc:
                    last_error = exc
            if body is None:
                raise RuntimeError(f"no se pudo leer calendario {cursor.year}-{cursor.month:02d}: {last_error}")
            pages.append((cursor.year, cursor.month, body))
            cursor = _next_month(cursor)
        events: list[RawNewsEvent] = []
        for year, month, body in pages:
            month_start = datetime(year, month, 1, tzinfo=UTC)
            next_month = _next_month(date(year, month, 1))
            month_end = datetime.combine(next_month, time.min, tzinfo=UTC) - timedelta(microseconds=1)
            parsed = parse_fed_month_calendar(body, year, month, month_start, month_end)
            plain = _html_text(body).lower()
            expected_labels = {
                "fomc meeting two-day meeting": "FOMC Interest Rate Decision / Statement",
                "fomc press conference": "FOMC Press Conference",
                "fomc minutes meeting of": "FOMC Minutes",
            }
            titles = {str(item.get("title")) for item in parsed}
            missing = [title for marker, title in expected_labels.items() if marker in plain and title not in titles]
            if missing:
                raise RuntimeError(f"el calendario se recibió pero no se pudieron interpretar: {', '.join(missing)}")
            events.extend(item for item in parsed if start <= _parse_iso_utc(item["event_time"]) <= end)
        return events


def parse_bls_ics(body: str, start: datetime, end: datetime) -> list[RawNewsEvent]:
    lines = _unfold_ics(body)
    current: dict[str, tuple[str, dict[str, str]]] | None = None
    output: list[RawNewsEvent] = []
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                summary = _ics_value(current, "SUMMARY")
                dtstart = _ics_datetime(current.get("DTSTART"))
                if summary and dtstart and start <= dtstart <= end:
                    output.append(_common_event(
                        upstream="BLS",
                        title=summary,
                        event_time=dtstart,
                        external_hint=_ics_value(current, "UID") or f"{summary}:{dtstart.isoformat()}",
                        url=_ics_value(current, "URL") or "https://www.bls.gov/schedule/",
                    ))
            current = None
            continue
        if current is None or ":" not in line:
            continue
        left, value = line.split(":", 1)
        parts = left.split(";")
        key = parts[0].upper()
        params = {}
        for part in parts[1:]:
            if "=" in part:
                p_key, p_value = part.split("=", 1)
                params[p_key.upper()] = p_value
        current[key] = (value.replace("\\,", ",").replace("\\n", " "), params)
    return output


def parse_bea_release_dates(data: Any, start: datetime, end: datetime) -> list[RawNewsEvent]:
    if not isinstance(data, dict):
        raise RuntimeError("BEA devolvió un formato inesperado")
    output: list[RawNewsEvent] = []
    for release_name, payload in data.items():
        if release_name == "file_last_updated" or not isinstance(payload, dict):
            continue
        dates = payload.get("release_dates")
        if not isinstance(dates, list):
            continue
        seen: set[str] = set()
        for raw_date in dates:
            try:
                event_time = _parse_iso_utc(raw_date)
            except ValueError:
                continue
            marker = event_time.isoformat()
            if marker in seen or not (start <= event_time <= end):
                continue
            seen.add(marker)
            output.append(_common_event(
                upstream="BEA",
                title=str(release_name),
                event_time=event_time,
                external_hint=f"{release_name}:{marker}",
                url="https://www.bea.gov/news/schedule",
            ))
    return output


def parse_census_calendar(body: str, start: datetime, end: datetime) -> list[RawNewsEvent]:
    parser = _TableParser()
    parser.feed(body)
    output: list[RawNewsEvent] = []
    for row in parser.rows:
        if len(row) < 3:
            continue
        title, release_date, release_time = row[0], row[1], row[2]
        if not title or release_date.strip().lower() == "suspended":
            continue
        try:
            local_date = datetime.strptime(release_date.strip(), "%B %d, %Y").date()
            local_time = datetime.strptime(release_time.strip().upper(), "%I:%M %p").time()
        except ValueError:
            continue
        event_time = datetime.combine(local_date, local_time, tzinfo=US_EASTERN).astimezone(UTC)
        if not (start <= event_time <= end):
            continue
        identifier = row[4].strip() if len(row) > 4 and row[4].strip() else f"{title}:{event_time.isoformat()}"
        output.append(_common_event(
            upstream="CENSUS",
            title=title,
            event_time=event_time,
            external_hint=identifier,
            url="https://www.census.gov/economic-indicators/calendar-listview.html",
        ))
    return output


def parse_fed_month_calendar(body: str, year: int, month: int, start: datetime, end: datetime) -> list[RawNewsEvent]:
    text = _html_text(body)
    output: list[RawNewsEvent] = []

    # Decision/statement: official monthly pages identify the end day of each
    # two-day meeting. The statement is released at the listed 2:00 p.m. ET.
    meeting_re = re.compile(
        r"(?P<clock>\d{1,2}:\d{2}\s*[ap]\.m\.)\s+FOMC Meeting\s+Two-day meeting,\s+"
        r"(?P<month>[A-Za-z]+)\s*(?P<start_day>\d{1,2})\s*-\s*(?P<end_day>\d{1,2})",
        re.IGNORECASE,
    )
    for match in meeting_re.finditer(text):
        event_time = _fed_local_dt(year, month, int(match.group("end_day")), match.group("clock"))
        if start <= event_time <= end:
            output.append(_common_event(
                upstream="FED",
                title="FOMC Interest Rate Decision / Statement",
                event_time=event_time,
                external_hint=f"fomc-decision:{event_time.isoformat()}",
                url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            ))

    # Press conference date is printed immediately after the entry on monthly pages.
    press_re = re.compile(
        r"(?P<clock>\d{1,2}:\d{2}\s*[ap]\.m\.)\s+FOMC Press Conference(?:\s+YouTube)?\s+(?P<day>\d{1,2})(?=\s|$)",
        re.IGNORECASE,
    )
    for match in press_re.finditer(text):
        event_time = _fed_local_dt(year, month, int(match.group("day")), match.group("clock"))
        if start <= event_time <= end:
            output.append(_common_event(
                upstream="FED",
                title="FOMC Press Conference",
                event_time=event_time,
                external_hint=f"fomc-press:{event_time.isoformat()}",
                url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            ))

    minutes_re = re.compile(
        r"(?P<clock>\d{1,2}:\d{2}\s*[ap]\.m\.)\s+FOMC Minutes\s+Meeting of\s+[A-Za-z]+\s+\d{1,2}\s*-\s*\d{1,2}\s+(?P<day>\d{1,2})(?=\s|$)",
        re.IGNORECASE,
    )
    for match in minutes_re.finditer(text):
        event_time = _fed_local_dt(year, month, int(match.group("day")), match.group("clock"))
        if start <= event_time <= end:
            output.append(_common_event(
                upstream="FED",
                title="FOMC Minutes",
                event_time=event_time,
                external_hint=f"fomc-minutes:{event_time.isoformat()}",
                url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            ))
    return _dedupe_raw(output)


def merge_calendar_events(events: list[RawNewsEvent], start: datetime, end: datetime) -> list[RawNewsEvent]:
    normalized: list[NewsEventCreate] = []
    for raw in events:
        try:
            item = NewsEventCreate.model_validate(raw)
        except Exception:
            continue
        if item.currency.upper() != "USD" or not (start <= item.event_time <= end):
            continue
        item.impact = classify_impact(item.title, item.impact)
        normalized.append(item)

    # Official sources own the event time/title. FMP may enrich values and fills
    # events not present in the primary-source set (ISM, ADP, confidence, etc.).
    priority = {"FED": 0, "BLS": 1, "BEA": 2, "CENSUS": 3, "FMP": 10}
    groups: dict[tuple[str, str, str], list[NewsEventCreate]] = {}
    for item in normalized:
        minute = item.event_time.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
        key = (item.currency.upper(), canonical_event_family(item.title), minute)
        groups.setdefault(key, []).append(item)

    merged: list[RawNewsEvent] = []
    for (currency, family, minute), group in groups.items():
        group.sort(key=lambda item: priority.get(_upstream(item), 20))
        base = group[0]
        previous = base.previous_value
        forecast = base.forecast_value
        actual = base.actual_value
        upstream_sources: list[str] = []
        upstream_payloads: dict[str, Any] = {}
        for item in group:
            upstream = _upstream(item)
            if upstream not in upstream_sources:
                upstream_sources.append(upstream)
            payload = item.raw_payload_json or {}
            upstream_payloads[upstream] = payload
            previous = previous or item.previous_value
            forecast = forecast or item.forecast_value
            actual = actual or item.actual_value
        stable_id = f"torum:{currency}:{family}:{base.event_time.astimezone(UTC).strftime('%Y%m%d%H%M')}"
        merged_item = base.model_copy(update={
            "source": "TORUM_CALENDAR",
            "external_id": stable_id[:160],
            "impact": classify_impact(base.title, base.impact),
            "previous_value": previous,
            "forecast_value": forecast,
            "actual_value": actual,
            "raw_payload_json": {
                "family": family,
                "upstream_sources": upstream_sources,
                "upstream_payloads": upstream_payloads,
                "canonical_minute": minute,
            },
        })
        merged.append(merged_item.model_dump(mode="json"))

    merged.sort(key=lambda item: str(item["event_time"]))
    return merged


def _common_event(*, upstream: str, title: str, event_time: datetime, external_hint: str, url: str) -> RawNewsEvent:
    event_time = _ensure_utc(event_time)
    return {
        "source": upstream,
        "external_id": _stable_external(upstream, external_hint),
        "country": "United States",
        "currency": "USD",
        "impact": classify_impact(title),
        "title": title.strip(),
        "event_time": event_time.isoformat(),
        "url": url,
        "raw_payload_json": {"upstream_source": upstream, "upstream_id": external_hint},
    }


def _upstream(item: NewsEventCreate) -> str:
    payload = item.raw_payload_json or {}
    return str(payload.get("upstream_source") or item.source).upper()


def _stable_external(source: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()[:24]
    return f"{source.lower()}:{digest}"


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_iso_utc(value: object) -> datetime:
    raw = str(value or "").strip()
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _ensure_utc(parsed)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _unfold_ics(body: str) -> list[str]:
    lines: list[str] = []
    for raw in body.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw.strip("\r"))
    return lines


def _ics_value(event: dict[str, tuple[str, dict[str, str]]], key: str) -> str | None:
    value = event.get(key)
    return value[0].strip() if value and value[0].strip() else None


def _ics_datetime(value: tuple[str, dict[str, str]] | None) -> datetime | None:
    if not value:
        return None
    raw, params = value
    raw = raw.strip()
    if not raw:
        return None
    tz: ZoneInfo | Any = UTC if raw.endswith("Z") else ZoneInfo(params.get("TZID", "America/New_York"))
    clean = raw.rstrip("Z")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            parsed = datetime.strptime(clean, fmt)
            return parsed.replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            pass
    return None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append(html.unescape(value))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _html_text(body: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


def _fed_local_dt(year: int, month: int, day: int, clock: str) -> datetime:
    normalized = clock.lower().replace(".", "").replace(" ", "")
    parsed_time = datetime.strptime(normalized, "%I:%M%p").time()
    return datetime.combine(date(year, month, day), parsed_time, tzinfo=US_EASTERN).astimezone(UTC)


def _dedupe_raw(events: list[RawNewsEvent]) -> list[RawNewsEvent]:
    seen: set[tuple[str, str]] = set()
    output: list[RawNewsEvent] = []
    for event in events:
        key = (str(event.get("title")), str(event.get("event_time")))
        if key not in seen:
            seen.add(key)
            output.append(event)
    return output

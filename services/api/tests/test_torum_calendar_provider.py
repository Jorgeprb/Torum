from datetime import UTC, datetime

from app.news.impact_classifier import canonical_event_family, classify_impact
from app.news.providers.fmp_provider import FmpEconomicCalendarProvider
from app.news.schemas import NewsSettingsUpdate
from app.news.providers.torum_calendar_provider import (
    TorumCalendarProvider,
    merge_calendar_events,
    parse_bea_release_dates,
    parse_bls_ics,
    parse_census_calendar,
    parse_fed_month_calendar,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 31, 23, 59, tzinfo=UTC)


def test_impact_rules_keep_torum_authoritative() -> None:
    assert classify_impact("Consumer Price Index") == "HIGH"
    assert classify_impact("Employment Situation") == "HIGH"
    assert classify_impact("FOMC Press Conference") == "HIGH"
    assert classify_impact("Advance Monthly Sales for Retail and Food Services") == "HIGH"
    assert classify_impact("Advance Report on Durable Goods--Manufacturers' Shipments") == "HIGH"
    assert classify_impact("Building Permits", "HIGH") != "HIGH"
    assert classify_impact("Unknown Macro Release", "HIGH") == "HIGH"
    assert canonical_event_family("Nonfarm Payrolls") == "NFP"
    assert canonical_event_family("Employment Situation") == "NFP"


def test_parse_bls_ics_uses_eastern_time_and_high_classifier() -> None:
    body = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:cpi-aug\nDTSTART;TZID=America/New_York:20260812T083000\nSUMMARY:Consumer Price Index\nURL:https://www.bls.gov/cpi/\nEND:VEVENT\nEND:VCALENDAR\n"""
    events = parse_bls_ics(body, START, END)
    assert len(events) == 1
    assert events[0]["title"] == "Consumer Price Index"
    assert events[0]["event_time"] == "2026-08-12T12:30:00+00:00"
    assert events[0]["impact"] == "HIGH"


def test_parse_bea_json_filters_window_and_deduplicates() -> None:
    data = {
        "Gross Domestic Product": {"release_dates": ["2026-08-26T12:30:00+00:00", "2026-08-26T12:30:00+00:00"]},
        "Personal Income and Outlays": {"release_dates": ["2026-09-30T12:30:00+00:00"]},
        "file_last_updated": "2026-07-13T08:00:00",
    }
    events = parse_bea_release_dates(data, START, END)
    assert len(events) == 1
    assert events[0]["title"] == "Gross Domestic Product"
    assert events[0]["impact"] == "HIGH"


def test_parse_census_table_and_excludes_housing_from_high() -> None:
    body = """
    <table><tbody>
      <tr><td>Advance Monthly Sales for Retail and Food Services</td><td>August 14, 2026</td><td>8:30 AM</td><td>July 2026</td><td>A202608140830</td></tr>
      <tr><td>New Residential Construction (Building Permits, Housing Starts, and Housing Completions)</td><td>August 18, 2026</td><td>8:30 AM</td><td>July 2026</td><td>A202608180830</td></tr>
    </tbody></table>
    """
    events = parse_census_calendar(body, START, END)
    assert len(events) == 2
    assert events[0]["event_time"] == "2026-08-14T12:30:00+00:00"
    assert events[0]["impact"] == "HIGH"
    assert events[1]["impact"] != "HIGH"


def test_parse_fed_month_calendar_decision_press_and_minutes() -> None:
    body = """
      <div>2:00 p.m. FOMC Minutes Meeting of July 28-29 19</div>
      <div>2:30 p.m. FOMC Press Conference YouTube 0</div>
    """
    # Minutes are a real parsable August event; the invalid day zero is ignored
    # by keeping this test focused on minutes. Decision/press are covered below.
    events = parse_fed_month_calendar(body.replace("YouTube 0", "YouTube 19"), 2026, 8, START, END)
    titles = {event["title"] for event in events}
    assert "FOMC Minutes" in titles
    assert "FOMC Press Conference" in titles
    assert all(event["impact"] == "HIGH" for event in events)

    september = "2:30 p.m. FOMC Press Conference YouTube 16 2:00 p.m. FOMC Meeting Two-day meeting, September 15 - 16 Press Conference 16"
    sept_events = parse_fed_month_calendar(
        september,
        2026,
        9,
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
    )
    assert {event["title"] for event in sept_events} == {"FOMC Interest Rate Decision / Statement", "FOMC Press Conference"}


def test_fmp_normalization_is_optional_enrichment_shape() -> None:
    provider = FmpEconomicCalendarProvider(api_key="test")
    event = provider.normalize({
        "date": "2026-08-12 12:30:00",
        "country": "US",
        "currency": "USD",
        "event": "CPI YoY",
        "impact": "High",
        "previous": 2.6,
        "estimate": 2.7,
        "actual": 2.8,
    })
    assert event.event_time == datetime(2026, 8, 12, 12, 30, tzinfo=UTC)
    assert event.impact == "HIGH"
    assert event.previous_value == "2.6"
    assert event.forecast_value == "2.7"
    assert event.actual_value == "2.8"


def test_merge_prefers_official_schedule_and_uses_fmp_values() -> None:
    official = {
        "source": "BLS",
        "external_id": "bls:1",
        "country": "United States",
        "currency": "USD",
        "impact": "HIGH",
        "title": "Consumer Price Index",
        "event_time": "2026-08-12T12:30:00+00:00",
        "raw_payload_json": {"upstream_source": "BLS"},
    }
    fmp = {
        "source": "FMP",
        "external_id": "fmp:1",
        "country": "US",
        "currency": "USD",
        "impact": "High",
        "title": "CPI YoY",
        "event_time": "2026-08-12T12:30:00+00:00",
        "previous_value": "2.6",
        "forecast_value": "2.7",
        "actual_value": "2.8",
        "raw_payload_json": {"provider": "FMP"},
    }
    merged = merge_calendar_events([fmp, official], START, END)
    assert len(merged) == 1
    assert merged[0]["source"] == "TORUM_CALENDAR"
    assert merged[0]["title"] == "Consumer Price Index"
    assert merged[0]["forecast_value"] == "2.7"
    assert merged[0]["raw_payload_json"]["upstream_sources"] == ["BLS", "FMP"]


def test_hybrid_provider_survives_one_source_failure(monkeypatch) -> None:
    provider = TorumCalendarProvider(timeout_seconds=0.1)
    monkeypatch.setattr(provider, "_fetch_bls", lambda start, end: [{
        "source": "BLS",
        "external_id": "bls:test",
        "country": "United States",
        "currency": "USD",
        "impact": "HIGH",
        "title": "Consumer Price Index",
        "event_time": "2026-08-12T12:30:00+00:00",
        "raw_payload_json": {"upstream_source": "BLS"},
    }])
    monkeypatch.setattr(provider, "_fetch_bea", lambda start, end: [])
    monkeypatch.setattr(provider, "_fetch_fed", lambda start, end: (_ for _ in ()).throw(RuntimeError("temporary")))
    monkeypatch.setattr(provider, "_fetch_census", lambda start, end: [])

    events = provider.fetch_events(START, END)
    assert len(events) == 1
    assert provider.safe_to_reconcile is False
    assert any("FED" in warning for warning in provider.warnings)


def test_legacy_finnhub_setting_is_normalized_to_torum() -> None:
    assert NewsSettingsUpdate(provider="FINNHUB").provider == "TORUM"
    assert NewsSettingsUpdate(provider="TORUM").provider == "TORUM"

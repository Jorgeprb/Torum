from __future__ import annotations

import re

NOT_HIGH_PATTERNS = [
    r"\bbuilding permits?\b",
    r"\bhousing starts?\b",
    r"\bnew (?:residential|home) sales\b",
    r"\bexisting home sales\b",
    r"\bpending home sales\b",
    r"\bs&p global .*pmi final\b",
    r"\bmarkit .*pmi final\b",
    r"\bmanufacturing pmi final\b",
    r"\bservices pmi final\b",
    r"\bcomposite pmi final\b",
]

HIGH_IMPACT_PATTERNS = [
    r"\bemployment situation\b",
    r"\bnon[-\s]?farm payrolls?\b",
    r"\bnfp\b",
    r"\bnonfarm employment\b",
    r"\bnon-farm employment\b",
    r"\bunemployment rate\b",
    r"\binitial jobless claims\b",
    r"\bcontinuing jobless claims\b",
    r"\bconsumer price index\b",
    r"\bcore cpi\b",
    r"\bcpi\b",
    r"\bproducer price index\b",
    r"\bcore ppi\b",
    r"\bppi\b",
    r"\bpce price index\b",
    r"\bcore pce\b",
    r"\bpersonal consumption expenditures\b",
    r"\bpersonal income and outlays\b",
    r"\bfed interest rate decision\b",
    r"\bfederal funds rate\b",
    r"\binterest rate decision\b",
    r"\brate decision\b",
    r"\bfomc\b",
    r"\bfomc statement\b",
    r"\bfomc minutes\b",
    r"\bfomc meeting\b",
    r"\bfomc press conference\b",
    r"\bfed press conference\b",
    r"\bfed chair\b",
    r"\bpowell\b",
    r"\bgross domestic product\b",
    r"\bgdp\b",
    r"\badvance monthly sales for retail and food services\b",
    r"\bretail sales\b",
    r"\bcore retail sales\b",
    r"\bism manufacturing\b",
    r"\bism services\b",
    r"\bism non[-\s]?manufacturing\b",
    r"\bjob openings and labor turnover survey\b",
    r"\bjolts\b",
    r"\badp employment\b",
    r"\badvance report on durable goods\b",
    r"\bdurable goods orders\b",
    r"\bconsumer confidence\b",
    r"\bmichigan consumer sentiment\b",
]

MEDIUM_IMPACT_PATTERNS = [
    r"\bu\.s\. international trade\b",
    r"\binternational trade in goods and services\b",
    r"\bindustrial production\b",
    r"\bbeige book\b",
    r"\bconstruction spending\b",
    r"\bmanufacturing and trade\b",
    r"\bwholesale trade\b",
    r"\bbusiness formation statistics\b",
]

FAMILY_PATTERNS: list[tuple[str, list[str]]] = [
    ("NFP", [r"\bemployment situation\b", r"\bnon[-\s]?farm payrolls?\b", r"\bnfp\b", r"\bnonfarm employment\b"]),
    ("CPI", [r"\bconsumer price index\b", r"\bcore cpi\b", r"\bcpi\b"]),
    ("PPI", [r"\bproducer price index\b", r"\bcore ppi\b", r"\bppi\b"]),
    ("PCE", [r"\bpersonal income and outlays\b", r"\bpce price index\b", r"\bcore pce\b", r"\bpersonal consumption expenditures\b"]),
    ("GDP", [r"\bgross domestic product\b", r"\bgdp\b"]),
    ("JOLTS", [r"\bjob openings and labor turnover survey\b", r"\bjolts\b"]),
    ("RETAIL_SALES", [r"\badvance monthly sales for retail and food services\b", r"\bretail sales\b"]),
    ("DURABLE_GOODS", [r"\badvance report on durable goods\b", r"\bdurable goods orders\b"]),
    ("FOMC_MINUTES", [r"\bfomc minutes\b"]),
    ("FOMC_PRESS", [r"\bfomc press conference\b", r"\bfed press conference\b"]),
    ("FOMC_DECISION", [r"\bfomc meeting\b", r"\bfomc statement\b", r"\bfed interest rate decision\b", r"\bfederal funds rate\b"]),
    ("JOBLESS_CLAIMS", [r"\binitial jobless claims\b", r"\bcontinuing jobless claims\b"]),
    ("ISM_MANUFACTURING", [r"\bism manufacturing\b"]),
    ("ISM_SERVICES", [r"\bism services\b", r"\bism non[-\s]?manufacturing\b"]),
    ("ADP", [r"\badp employment\b"]),
    ("CONSUMER_CONFIDENCE", [r"\bconsumer confidence\b"]),
    ("MICHIGAN_SENTIMENT", [r"\bmichigan consumer sentiment\b"]),
]


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def normalize_provider_impact(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw in {"HIGH", "3", "RED"}:
        return "HIGH"
    if raw in {"MEDIUM", "MODERATE", "2", "ORANGE", "YELLOW"}:
        return "MEDIUM"
    if raw in {"LOW", "1", "GREEN"}:
        return "LOW"
    return None


def classify_impact(title: str, provided_impact: object = None) -> str:
    """Classify news consistently for Torum.

    Explicit Torum exclusions win over provider labels. Known high-impact events
    are promoted to HIGH even if an upstream provider labels them differently.
    For events not covered by Torum rules, a normalized provider impact is used
    as a hint, otherwise the event falls back to LOW.
    """
    text = str(title or "").strip().lower()
    if _matches(text, NOT_HIGH_PATTERNS):
        return "MEDIUM" if _matches(text, MEDIUM_IMPACT_PATTERNS) else "LOW"
    if _matches(text, HIGH_IMPACT_PATTERNS):
        return "HIGH"
    provider_impact = normalize_provider_impact(provided_impact)
    if provider_impact is not None:
        return provider_impact
    if _matches(text, MEDIUM_IMPACT_PATTERNS):
        return "MEDIUM"
    return "LOW"


def canonical_event_family(title: str) -> str:
    text = str(title or "").strip().lower()
    for family, patterns in FAMILY_PATTERNS:
        if _matches(text, patterns):
            return family
    compact = re.sub(r"[^A-Z0-9]+", "_", str(title or "").upper()).strip("_")
    return compact[:72] or "UNKNOWN"

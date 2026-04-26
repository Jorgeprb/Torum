from datetime import UTC, datetime
from typing import Any

DRAWING_TYPES = {"horizontal_line", "vertical_line", "trend_line", "rectangle", "text", "manual_zone"}
DRAWING_SOURCES = {"MANUAL", "INDICATOR", "NEWS", "STRATEGY", "IMPORT"}
ZONE_DIRECTIONS = {"BUY", "SELL", "NEUTRAL"}

DEFAULT_STYLE: dict[str, Any] = {
    "color": "#f5c542",
    "lineWidth": 2,
    "lineStyle": "solid",
    "backgroundColor": "rgba(245,197,66,0.15)",
    "textColor": "#ffffff",
}


class DrawingValidationError(ValueError):
    pass


def normalize_unix_time(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise DrawingValidationError(f"{field_name} must be a Unix timestamp or ISO datetime")
    if isinstance(value, int | float):
        timestamp = int(value)
        if timestamp <= 0:
            raise DrawingValidationError(f"{field_name} must be positive")
        return timestamp
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise DrawingValidationError(f"{field_name} cannot be empty")
        if raw.replace(".", "", 1).isdigit():
            return normalize_unix_time(float(raw), field_name)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    raise DrawingValidationError(f"{field_name} must be a Unix timestamp or ISO datetime")


def require_number(payload: dict[str, Any], field_name: str) -> float:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DrawingValidationError(f"{field_name} must be numeric")
    return float(value)


def normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DrawingValidationError("label must be a string")
    label = value.strip()
    return label or None


def _with_label(payload: dict[str, Any]) -> dict[str, Any]:
    label = normalize_label(payload.get("label"))
    return {"label": label} if label else {}


def validate_drawing_payload(drawing_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if drawing_type not in DRAWING_TYPES:
        raise DrawingValidationError(f"Unsupported drawing_type: {drawing_type}")
    if not isinstance(payload, dict):
        raise DrawingValidationError("payload must be an object")

    if drawing_type == "horizontal_line":
        return {"price": require_number(payload, "price"), **_with_label(payload)}

    if drawing_type == "vertical_line":
        return {"time": normalize_unix_time(payload.get("time"), "time"), **_with_label(payload)}

    if drawing_type == "trend_line":
        points = payload.get("points")
        if not isinstance(points, list) or len(points) != 2:
            raise DrawingValidationError("trend_line points must contain exactly two points")
        normalized_points: list[dict[str, float | int]] = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                raise DrawingValidationError(f"points[{index}] must be an object")
            normalized_points.append(
                {
                    "time": normalize_unix_time(point.get("time"), f"points[{index}].time"),
                    "price": require_number(point, "price"),
                }
            )
        return {"points": normalized_points, **_with_label(payload)}

    if drawing_type == "rectangle":
        time1 = normalize_unix_time(payload.get("time1"), "time1")
        time2 = normalize_unix_time(payload.get("time2"), "time2")
        if time1 == time2:
            raise DrawingValidationError("time2 must be different from time1")
        price1 = require_number(payload, "price1")
        price2 = require_number(payload, "price2")
        if price1 == price2:
            raise DrawingValidationError("price1 and price2 must be different")
        return {
            "time1": min(time1, time2),
            "time2": max(time1, time2),
            "price1": min(price1, price2),
            "price2": max(price1, price2),
            **_with_label(payload),
        }

    if drawing_type == "text":
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise DrawingValidationError("text must be a non-empty string")
        return {
            "time": normalize_unix_time(payload.get("time"), "time"),
            "price": require_number(payload, "price"),
            "text": text.strip(),
        }

    time1 = normalize_unix_time(payload.get("time1"), "time1")
    raw_time2 = payload.get("time2")
    time2 = None if raw_time2 is None else normalize_unix_time(raw_time2, "time2")
    if time2 is not None and time2 <= time1:
        raise DrawingValidationError("time2 must be greater than time1")
    price_min = require_number(payload, "price_min")
    price_max = require_number(payload, "price_max")
    if price_max <= price_min:
        raise DrawingValidationError("price_max must be greater than price_min")
    direction = str(payload.get("direction") or "NEUTRAL").upper()
    if direction not in ZONE_DIRECTIONS:
        raise DrawingValidationError("direction must be BUY, SELL or NEUTRAL")
    rules = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "time1": time1,
        "time2": time2,
        "price_min": price_min,
        "price_max": price_max,
        "direction": direction,
        "label": normalize_label(payload.get("label")) or "Manual zone",
        "rules": rules,
        "metadata": metadata,
    }


def normalize_style(style: dict[str, Any] | None) -> dict[str, Any]:
    if style is None:
        return dict(DEFAULT_STYLE)
    if not isinstance(style, dict):
        raise DrawingValidationError("style must be an object")
    normalized = {**DEFAULT_STYLE, **style}
    if not isinstance(normalized.get("color"), str):
        raise DrawingValidationError("style.color must be a string")
    if not isinstance(normalized.get("lineWidth"), int | float):
        raise DrawingValidationError("style.lineWidth must be numeric")
    normalized["lineWidth"] = max(1, min(6, int(normalized["lineWidth"])))
    return normalized

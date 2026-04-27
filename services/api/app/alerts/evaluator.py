from datetime import UTC, datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.alerts.repository import list_active_alerts_for_symbol
from app.alerts.schemas import PriceAlertTriggeredEvent
from app.alerts.push import PushNotificationService


def price_from_tick_row(row: dict[str, object]) -> float | None:
    bid = _float_or_none(row.get("bid"))
    ask = _float_or_none(row.get("ask"))
    last = _float_or_none(row.get("last"))
    if bid is not None:
        return bid
    if last is not None:
        return last
    if ask is not None:
        return ask
    return None


class PriceAlertEvaluator:
    def __init__(
        self,
        db: Session,
        *,
        push_service: PushNotificationService | None = None,
        on_trigger: Callable[[PriceAlertTriggeredEvent], None] | None = None,
    ) -> None:
        self.db = db
        self.push_service = push_service
        self.on_trigger = on_trigger

    def evaluate_inserted_ticks(self, inserted_rows: list[dict[str, object]]) -> list[PriceAlertTriggeredEvent]:
        latest_price_by_symbol: dict[str, tuple[datetime, float]] = {}
        for row in inserted_rows:
            symbol = str(row["internal_symbol"]).upper()
            price = price_from_tick_row(row)
            row_time = row.get("time")
            if price is None or not isinstance(row_time, datetime):
                continue
            current = latest_price_by_symbol.get(symbol)
            if current is None or row_time >= current[0]:
                latest_price_by_symbol[symbol] = (row_time, price)

        events: list[PriceAlertTriggeredEvent] = []
        for symbol, (checked_at, price) in latest_price_by_symbol.items():
            events.extend(self.evaluate_symbol(symbol=symbol, current_price=price, checked_at=checked_at))
        return events

    def evaluate_symbol(
        self,
        *,
        symbol: str,
        current_price: float,
        checked_at: datetime | None = None,
    ) -> list[PriceAlertTriggeredEvent]:
        now = checked_at or datetime.now(UTC)
        triggered: list[PriceAlertTriggeredEvent] = []
        alerts = list_active_alerts_for_symbol(self.db, symbol)
        for alert in alerts:
            alert.last_checked_price = current_price
            if alert.condition_type != "BELOW":
                continue
            if current_price > alert.target_price:
                continue
            if alert.status != "ACTIVE":
                continue
            alert.status = "TRIGGERED"
            alert.triggered_at = now
            alert.triggered_price = current_price
            event = PriceAlertTriggeredEvent(
                alert_id=alert.id,
                user_id=alert.user_id,
                symbol=alert.internal_symbol,
                timeframe=alert.timeframe,
                target_price=alert.target_price,
                triggered_price=current_price,
                triggered_at=now,
            )
            triggered.append(event)
        self.db.commit()
        for event in triggered:
            if self.on_trigger:
                self.on_trigger(event)
            if self.push_service:
                self.push_service.send_price_alert(event)
        return triggered


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

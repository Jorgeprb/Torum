from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.alerts.models import PriceAlert, PushSubscription
from app.alerts.repository import (
    get_push_subscription_by_endpoint,
    list_price_alerts,
)
from app.alerts.schemas import (
    PriceAlertCreate,
    PriceAlertRead,
    PriceAlertUpdate,
    PushSubscriptionCreate,
)
from app.symbols.models import SymbolMapping
from app.users.models import User, UserRole


class PriceAlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, *, user: User, symbol: str | None = None, status_filter: str | None = None) -> list[PriceAlert]:
        return list_price_alerts(self.db, user_id=user.id, symbol=symbol, status=status_filter)

    def history_for_user(self, *, user: User, symbol: str | None = None) -> list[PriceAlert]:
        return [
            alert
            for alert in list_price_alerts(self.db, user_id=user.id, symbol=symbol, include_deleted=True, limit=500)
            if alert.status != "ACTIVE"
        ]

    def create(self, payload: PriceAlertCreate, user: User) -> PriceAlert:
        self._ensure_can_mutate(user)
        self._ensure_symbol_exists(payload.internal_symbol)
        alert = PriceAlert(
            user_id=user.id,
            internal_symbol=payload.internal_symbol,
            timeframe=None,
            condition_type="BELOW",
            target_price=payload.target_price,
            status="ACTIVE",
            source=payload.source,
            message=payload.message,
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def update(self, alert: PriceAlert, payload: PriceAlertUpdate, user: User) -> PriceAlert:
        self._ensure_can_access(alert, user)
        self._ensure_can_mutate(user)
        if alert.status == "TRIGGERED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Triggered alerts cannot be edited")
        data = payload.model_dump(exclude_unset=True)
        if "target_price" in data and data["target_price"] is not None:
            alert.target_price = data["target_price"]
        if "message" in data:
            alert.message = data["message"]
        if data.get("status") == "CANCELLED":
            alert.status = "CANCELLED"
            alert.deleted_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def cancel(self, alert: PriceAlert, user: User) -> None:
        self._ensure_can_access(alert, user)
        self._ensure_can_mutate(user)
        if alert.status == "ACTIVE":
            alert.status = "CANCELLED"
        alert.deleted_at = datetime.now(UTC)
        self.db.commit()

    def to_read(self, alert: PriceAlert) -> PriceAlertRead:
        return PriceAlertRead.model_validate(alert)

    def _ensure_symbol_exists(self, symbol: str) -> None:
        mapping = self.db.query(SymbolMapping).filter(SymbolMapping.internal_symbol == symbol.upper()).one_or_none()
        if mapping is None or not mapping.enabled:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown or disabled symbol: {symbol}")

    def _ensure_can_mutate(self, user: User) -> None:
        if user.role not in {UserRole.admin, UserRole.trader}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User role cannot modify alerts")

    def _ensure_can_access(self, alert: PriceAlert, user: User) -> None:
        if user.role == UserRole.admin:
            return
        if alert.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")


class PushSubscriptionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, payload: PushSubscriptionCreate, user: User) -> PushSubscription:
        subscription = get_push_subscription_by_endpoint(self.db, user_id=user.id, endpoint=payload.endpoint)
        if subscription is None:
            subscription = PushSubscription(
                user_id=user.id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
                user_agent=payload.user_agent,
                device_name=payload.device_name,
                enabled=True,
            )
            self.db.add(subscription)
        else:
            subscription.p256dh = payload.keys.p256dh
            subscription.auth = payload.keys.auth
            subscription.user_agent = payload.user_agent
            subscription.device_name = payload.device_name
            subscription.enabled = True
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

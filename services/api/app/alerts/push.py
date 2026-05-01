from datetime import UTC, datetime
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.alerts.models import PushSubscription
from app.alerts.repository import list_push_subscriptions
from app.alerts.schemas import PriceAlertTriggeredEvent
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PushNotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def send_price_alert(self, event: PriceAlertTriggeredEvent) -> tuple[int, int]:
        payload = {
            "title": f"Torum alerta {event.symbol}",
            "body": f"Precio <= {event.target_price:.2f}. Actual: {event.triggered_price:.2f}",
            "url": f"/?symbol={event.symbol}",
            "data": event.model_dump(mode="json"),
        }
        return self._send_to_user(event.user_id, payload)

    def send_test(self, user_id: int) -> tuple[int, int]:
        payload = {
            "title": "Torum push activo",
            "body": "Notificacion de prueba enviada desde Torum.",
            "url": "/",
            "data": {"type": "push_test"},
        }
        return self._send_to_user(user_id, payload)

    def _send_to_user(self, user_id: int, payload: dict[str, Any]) -> tuple[int, int]:
        subscriptions = list_push_subscriptions(self.db, user_id=user_id, enabled_only=True)
        if not subscriptions:
            return 0, 0

        settings = get_settings()
        private_key = settings.vapid_private_key.get_secret_value() if settings.vapid_private_key else None
        if not settings.vapid_public_key or not private_key:
            logger.warning("PWA push skipped because VAPID keys are not configured")
            return 0, len(subscriptions)

        sent = 0
        failed = 0
        for subscription in subscriptions:
            ok = self._send_one(subscription, payload, private_key, settings.vapid_subject)
            if ok:
                sent += 1
            else:
                failed += 1
        self.db.commit()
        return sent, failed

    def _send_one(self, subscription: PushSubscription, payload: dict[str, Any], private_key: str, subject: str) -> bool:
        try:
            from pywebpush import WebPushException, webpush

            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=json.dumps(payload),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                ttl=60,
                headers={"Urgency": "high"},
            )
            subscription.last_used_at = datetime.now(UTC)
            return True
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                subscription.enabled = False
            if exc.__class__.__name__ == "WebPushException":
                logger.warning("PWA push failed for subscription %s: %s", subscription.id, exc)
            else:
                logger.exception("Unexpected PWA push failure for subscription %s", subscription.id)
            return False

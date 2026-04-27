from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.alerts.push import PushNotificationService
from app.alerts.repository import get_price_alert, get_push_subscription, list_push_subscriptions
from app.alerts.schemas import (
    PriceAlertCreate,
    PriceAlertRead,
    PriceAlertUpdate,
    PushSubscriptionCreate,
    PushSubscriptionRead,
    PushTestResponse,
)
from app.alerts.service import PriceAlertService, PushSubscriptionService
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.users.models import User

router = APIRouter(tags=["alerts"])


@router.get("/alerts/price", response_model=list[PriceAlertRead])
def list_price_alerts(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None, min_length=3),
    status_filter: str | None = Query(default="ACTIVE", alias="status"),
) -> list[PriceAlertRead]:
    service = PriceAlertService(db)
    return [service.to_read(alert) for alert in service.list_for_user(user=current_user, symbol=symbol, status_filter=status_filter)]


@router.get("/alerts/price/history", response_model=list[PriceAlertRead])
def price_alert_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    symbol: str | None = Query(default=None, min_length=3),
) -> list[PriceAlertRead]:
    service = PriceAlertService(db)
    return [service.to_read(alert) for alert in service.history_for_user(user=current_user, symbol=symbol)]


@router.post("/alerts/price", response_model=PriceAlertRead, status_code=status.HTTP_201_CREATED)
def create_price_alert(
    payload: PriceAlertCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PriceAlertRead:
    service = PriceAlertService(db)
    return service.to_read(service.create(payload, current_user))


@router.patch("/alerts/price/{alert_id}", response_model=PriceAlertRead)
def update_price_alert(
    alert_id: str,
    payload: PriceAlertUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PriceAlertRead:
    alert = get_price_alert(db, alert_id)
    if alert is None or alert.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price alert not found")
    service = PriceAlertService(db)
    return service.to_read(service.update(alert, payload, current_user))


@router.delete("/alerts/price/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_price_alert(
    alert_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    alert = get_price_alert(db, alert_id)
    if alert is None or alert.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price alert not found")
    PriceAlertService(db).cancel(alert, current_user)


@router.get("/push/vapid-public-key")
def get_vapid_public_key() -> dict[str, str | None]:
    return {"public_key": get_settings().vapid_public_key}


@router.post("/push/subscribe", response_model=PushSubscriptionRead, status_code=status.HTTP_201_CREATED)
def subscribe_push(
    payload: PushSubscriptionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PushSubscriptionRead:
    return PushSubscriptionRead.model_validate(PushSubscriptionService(db).upsert(payload, current_user))


@router.get("/push/subscriptions", response_model=list[PushSubscriptionRead])
def get_push_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[PushSubscriptionRead]:
    return [PushSubscriptionRead.model_validate(item) for item in list_push_subscriptions(db, user_id=current_user.id)]


@router.delete("/push/subscribe/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_subscription(
    subscription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    subscription = get_push_subscription(db, subscription_id)
    if subscription is None or subscription.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Push subscription not found")
    subscription.enabled = False
    db.commit()


@router.post("/push/test", response_model=PushTestResponse)
def send_push_test(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PushTestResponse:
    sent, failed = PushNotificationService(db).send_test(current_user.id)
    return PushTestResponse(
        ok=sent > 0 and failed == 0,
        sent=sent,
        failed=failed,
        message="Push test sent" if sent else "No push notification was sent",
    )

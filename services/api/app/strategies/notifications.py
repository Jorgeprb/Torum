from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.push import PushNotificationService
from app.alerts.repository import list_users_with_enabled_push
from app.db.session import SessionLocal
from app.strategies.models import StrategyUnlockNotification
from app.strategies.torum_v1 import MADRID_TZ, SUPPORTED_SYMBOLS, TORUM_V1_KEY, TorumV1StatusService

logger = logging.getLogger(__name__)


def notify_torum_v1_unlocks_for_symbols(symbols: list[str]) -> None:
    normalized_symbols = _supported_symbols(symbols)
    if not normalized_symbols:
        return

    with SessionLocal() as db:
        send_torum_v1_unlock_notifications(db, symbols=normalized_symbols)


def send_torum_v1_unlock_notifications(
    db: Session,
    *,
    symbols: list[str] | None = None,
    at_time: datetime | None = None,
) -> int:
    normalized_symbols = _supported_symbols(symbols or list(SUPPORTED_SYMBOLS))
    if not normalized_symbols:
        return 0

    checked_at = _as_utc(at_time or datetime.now(UTC))
    unlock_day = checked_at.astimezone(MADRID_TZ).date()
    users = list_users_with_enabled_push(db)
    if not users:
        return 0

    status_service = TorumV1StatusService(db)
    push_service = PushNotificationService(db)
    sent_notifications = 0

    for user in users:
        status = status_service.status_for_user(user.id, checked_at)
        for symbol in normalized_symbols:
            asset = status.assets.get(symbol)
            if asset is None or asset.status != "UNLOCKED" or asset.unlocked_at is None:
                continue
            if _already_sent(db, user.id, symbol, unlock_day):
                continue

            sent, _failed = push_service.send_torum_v1_unlocked(user.id, symbol, unlock_day.isoformat())
            if sent <= 0:
                continue

            notification = StrategyUnlockNotification(
                user_id=user.id,
                strategy_key=TORUM_V1_KEY,
                internal_symbol=symbol,
                unlock_day=unlock_day,
                unlocked_at=asset.unlocked_at,
                sent_at=checked_at,
            )
            db.add(notification)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue
            except Exception:
                db.rollback()
                logger.exception("Could not store Torum V1 unlock notification for user=%s symbol=%s", user.id, symbol)
                continue
            sent_notifications += 1

    return sent_notifications


def _already_sent(db: Session, user_id: int, symbol: str, unlock_day: object) -> bool:
    return (
        db.scalar(
            select(StrategyUnlockNotification.id).where(
                StrategyUnlockNotification.user_id == user_id,
                StrategyUnlockNotification.strategy_key == TORUM_V1_KEY,
                StrategyUnlockNotification.internal_symbol == symbol,
                StrategyUnlockNotification.unlock_day == unlock_day,
            )
        )
        is not None
    )


def _supported_symbols(symbols: list[str]) -> list[str]:
    supported = set(SUPPORTED_SYMBOLS)
    return sorted({symbol.upper() for symbol in symbols if symbol and symbol.upper() in supported})


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

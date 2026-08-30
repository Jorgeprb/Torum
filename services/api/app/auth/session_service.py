from datetime import UTC, datetime
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.users.models import User

_SESSION_TOKEN_BYTES = 48


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_persistent_session(db: Session, user: User) -> str:
    """Create a revocable, non-expiring Torum session and return its opaque secret once."""
    token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
    record = AuthSession(user_id=user.id, token_hash=_token_hash(token))
    db.add(record)
    db.commit()
    return token


def resolve_persistent_session(db: Session, token: str) -> User | None:
    if not token:
        return None

    record = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if record is None:
        return None

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None

    record.last_used_at = datetime.now(UTC)
    db.commit()
    return user


def revoke_persistent_session(db: Session, token: str) -> None:
    if not token:
        return

    record = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if record is None:
        return

    record.revoked_at = datetime.now(UTC)
    db.commit()

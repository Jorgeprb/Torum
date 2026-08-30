from datetime import UTC, datetime
import hashlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.auth.session_service import create_persistent_session, resolve_persistent_session, revoke_persistent_session
from app.db.base import Base
from app.users.models import User, UserRole


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, AuthSession.__table__])
    return Session(engine, expire_on_commit=False)


def _user(db: Session) -> User:
    user = User(
        username="persistent-user",
        email="persistent@example.com",
        hashed_password="not-used-by-this-test",
        role=UserRole.trader,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_persistent_session_is_hashed_resolvable_and_revocable() -> None:
    with _db() as db:
        user = _user(db)
        token = create_persistent_session(db, user)

        assert token
        record = db.scalar(select(AuthSession))
        assert record is not None
        assert record.token_hash != token
        assert record.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert record.revoked_at is None

        before = record.last_used_at
        resolved = resolve_persistent_session(db, token)
        assert resolved is not None
        assert resolved.id == user.id
        db.refresh(record)
        assert record.last_used_at >= before

        revoke_persistent_session(db, token)
        db.refresh(record)
        assert record.revoked_at is not None
        assert resolve_persistent_session(db, token) is None


def test_persistent_session_rejects_inactive_user_without_expiring_by_time() -> None:
    with _db() as db:
        user = _user(db)
        token = create_persistent_session(db, user)

        record = db.scalar(select(AuthSession))
        assert record is not None
        # There is intentionally no expires_at field: validity ends only by
        # explicit revocation, user deactivation, or deleting browser storage.
        assert not hasattr(record, "expires_at")
        assert resolve_persistent_session(db, token) is not None

        user.is_active = False
        user.updated_at = datetime.now(UTC)
        db.commit()
        assert resolve_persistent_session(db, token) is None

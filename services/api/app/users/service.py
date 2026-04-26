import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import get_password_hash
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def create_user(db: Session, username: str, email: str, password: str, role: UserRole) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_initial_users() -> None:
    settings = get_settings()
    users_to_seed = [
        (
            settings.initial_admin_username,
            settings.initial_admin_email,
            settings.initial_admin_password.get_secret_value(),
            UserRole.admin,
        ),
        (
            settings.initial_trader_username,
            settings.initial_trader_email,
            settings.initial_trader_password.get_secret_value(),
            UserRole.trader,
        ),
    ]

    with SessionLocal() as db:
        for username, email, password, role in users_to_seed:
            existing_user = get_user_by_username(db, username)
            if existing_user is not None:
                continue
            create_user(db, username=username, email=email, password=password, role=role)
            logger.info("Created initial %s user '%s'", role.value, username)

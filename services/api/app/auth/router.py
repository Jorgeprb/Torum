from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    LoginRequest,
    SessionBootstrapResponse,
    SessionLogoutRequest,
    SessionRefreshRequest,
    SessionRefreshResponse,
    TokenResponse,
)
from app.auth.security import create_access_token, verify_password
from app.auth.session_service import create_persistent_session, resolve_persistent_session, revoke_persistent_session
from app.db.session import get_db
from app.users.models import User
from app.users.schemas import UserRead
from app.users.service import get_user_by_username

router = APIRouter(prefix="/auth", tags=["auth"])


def _access_token_for(user: User) -> str:
    return create_access_token(subject=user.username, extra_claims={"role": user.role.value})


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    user = get_user_by_username(db, payload.username)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    session_token = create_persistent_session(db, user)
    return TokenResponse(
        access_token=_access_token_for(user),
        session_token=session_token,
        user=UserRead.model_validate(user),
    )


@router.post("/session", response_model=SessionBootstrapResponse)
def create_session_from_current_login(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionBootstrapResponse:
    return SessionBootstrapResponse(session_token=create_persistent_session(db, current_user))


@router.post("/refresh", response_model=SessionRefreshResponse)
def refresh_session(
    payload: SessionRefreshRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SessionRefreshResponse:
    user = resolve_persistent_session(db, payload.session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked session",
        )
    return SessionRefreshResponse(access_token=_access_token_for(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_session(
    payload: SessionLogoutRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    # Deliberately idempotent: callers can always clear their local session,
    # even if the token was already revoked or unknown.
    revoke_persistent_session(db, payload.session_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(current_user)

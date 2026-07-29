from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

SERVICE_TOKEN_HEADER = "X-Torum-Service-Token"


def require_service_token(
    token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> None:
    settings = get_settings()
    if not settings.internal_auth_required:
        return
    configured = settings.service_token.get_secret_value() if settings.service_token else ""
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal service token is not configured",
        )
    if token is None or not secrets.compare_digest(token, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal service token")

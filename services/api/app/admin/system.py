import logging
from time import perf_counter
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.users.models import User, UserRole

router = APIRouter(prefix="/admin/system", tags=["admin-system"])
logger = logging.getLogger(__name__)

RestartTarget = Literal["mt5", "api", "frontend", "bridge", "all", "pc"]
ALLOWED_TARGETS: set[str] = {"mt5", "api", "frontend", "bridge", "all", "pc"}


class RestartRequest(BaseModel):
    confirmation: str


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def watchdog_headers() -> dict[str, str]:
    settings = get_settings()
    if settings.watchdog_admin_token is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Watchdog token not configured")
    return {"Authorization": f"Bearer {settings.watchdog_admin_token.get_secret_value()}"}


def watchdog_url(path: str) -> str:
    settings = get_settings()
    if not settings.watchdog_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Watchdog base URL not configured")
    return f"{settings.watchdog_base_url.rstrip('/')}{path}"


def watchdog_timeout() -> float:
    return get_settings().watchdog_timeout_seconds


def proxy_error(path: str, exc: requests.RequestException, duration_ms: float) -> HTTPException:
    logger.warning(
        "watchdog_proxy_unreachable path=%s base_url=%s duration_ms=%.1f error=%s",
        path,
        get_settings().watchdog_base_url,
        duration_ms,
        exc,
    )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Watchdog unreachable: {exc}")


@router.get("/status")
def system_status(_: User = Depends(require_admin)) -> dict:
    path = "/status"
    url = watchdog_url(path)
    timeout = watchdog_timeout()
    started = perf_counter()
    logger.info(
        "watchdog_proxy_request method=GET path=%s base_url=%s timeout_seconds=%.1f",
        path,
        get_settings().watchdog_base_url,
        timeout,
    )
    try:
        response = requests.get(url, headers=watchdog_headers(), timeout=timeout)
    except requests.RequestException as exc:
        raise proxy_error(path, exc, (perf_counter() - started) * 1000) from exc
    duration_ms = (perf_counter() - started) * 1000
    if response.status_code >= 400:
        logger.warning("watchdog_proxy_error path=%s status=%s duration_ms=%.1f", path, response.status_code, duration_ms)
        raise HTTPException(status_code=response.status_code, detail=response.text)
    logger.info("watchdog_proxy_response path=%s status=%s duration_ms=%.1f", path, response.status_code, duration_ms)
    return response.json()


@router.post("/restart/{target}")
def restart_target(target: RestartTarget, payload: RestartRequest, _: User = Depends(require_admin)) -> dict:
    if target not in ALLOWED_TARGETS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown restart target")
    expected = "REINICIAR PC" if target == "pc" else "REINICIAR"
    if payload.confirmation.strip().upper() != expected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Confirmacion requerida: {expected}")
    path = f"/restart/{target}"
    url = watchdog_url(path)
    timeout = max(watchdog_timeout(), 30.0)
    started = perf_counter()
    logger.info("watchdog_proxy_request method=POST path=%s base_url=%s timeout_seconds=%.1f", path, get_settings().watchdog_base_url, timeout)
    try:
        response = requests.post(
            url,
            headers=watchdog_headers(),
            json={"confirmation": payload.confirmation},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise proxy_error(path, exc, (perf_counter() - started) * 1000) from exc
    duration_ms = (perf_counter() - started) * 1000
    if response.status_code >= 400:
        logger.warning("watchdog_proxy_error path=%s status=%s duration_ms=%.1f", path, response.status_code, duration_ms)
        raise HTTPException(status_code=response.status_code, detail=response.text)
    logger.info("watchdog_proxy_response path=%s status=%s duration_ms=%.1f", path, response.status_code, duration_ms)
    return response.json()

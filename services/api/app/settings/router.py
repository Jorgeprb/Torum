from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/system/status")
def system_status() -> dict[str, object]:
    settings = get_settings()
    return {
        "project": settings.project_name,
        "environment": settings.environment,
        "tailscale_enabled": settings.tailscale_enabled,
        "public_host": settings.public_host,
        "trading_mode": settings.trading_mode,
        "mt5_bridge_configured": bool(settings.mt5_bridge_base_url),
        "roles": ["admin", "trader"],
    }

import logging
from typing import Any

import requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MT5BridgeClientError(RuntimeError):
    pass


class MT5BridgeClient:
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.mt5_bridge_base_url or "").rstrip("/")
        self.timeout = 10

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def health(self) -> dict[str, Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        response = requests.get(f"{self.base_url}/health", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_order_execution_settings(self) -> dict[str, Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        try:
            response = requests.get(f"{self.base_url}/settings/order-execution", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MT5 bridge order execution settings request failed: %s", exc)
            raise MT5BridgeClientError(str(exc)) from exc

    def set_order_execution_enabled(self, enabled: bool) -> dict[str, Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        try:
            response = requests.patch(
                f"{self.base_url}/settings/order-execution",
                json={"enabled": enabled},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MT5 bridge order execution settings update failed: %s", exc)
            raise MT5BridgeClientError(str(exc)) from exc

    def execute_market_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        try:
            response = requests.post(f"{self.base_url}/orders/market", json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MT5 bridge order request failed: %s", exc)
            raise MT5BridgeClientError(str(exc)) from exc

    def close_position(self, ticket: int, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        try:
            response = requests.post(f"{self.base_url}/positions/{ticket}/close", json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MT5 bridge close position failed: %s", exc)
            raise MT5BridgeClientError(str(exc)) from exc

from __future__ import annotations

import logging
from threading import local
from typing import Any

import requests

from app.core.config import get_settings
from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)


class MT5BridgeClientError(RuntimeError):
    pass


class MT5BridgeClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.mt5_bridge_base_url or "").rstrip("/")
        self.timeout = timeout
        self._token = settings.service_token.get_secret_value() if settings.service_token else ""
        self._local = local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            if self._token:
                session.headers.update({"X-Torum-Service-Token": self._token})
            self._local.session = session
        return session

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        if not self.is_configured():
            raise MT5BridgeClientError("MT5 bridge base URL is not configured")
        request_id = get_request_id()
        headers = dict(kwargs.pop("headers", {}) or {})
        if request_id:
            headers.setdefault("X-Request-ID", request_id)
        try:
            response = self._session().request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MT5 bridge %s %s failed: %s", method, path, exc)
            raise MT5BridgeClientError(str(exc)) from exc

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health")
        return payload if isinstance(payload, dict) else {}

    def get_order_execution_settings(self) -> dict[str, Any]:
        payload = self._request("GET", "/settings/order-execution")
        return payload if isinstance(payload, dict) else {}

    def set_order_execution_enabled(
        self,
        enabled: bool,
        *,
        allowed_account_modes: list[str] | None = None,
        enable_real_trading: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"enabled": enabled}
        if allowed_account_modes is not None:
            body["allowed_account_modes"] = allowed_account_modes
        if enable_real_trading is not None:
            body["enable_real_trading"] = enable_real_trading
        payload = self._request("PATCH", "/settings/order-execution", json=body)
        return payload if isinstance(payload, dict) else {}

    def execute_market_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/orders/market", json=payload)
        return response if isinstance(response, dict) else {}

    def get_positions(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/positions")
        return response if isinstance(response, list) else []

    def close_position(self, ticket: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", f"/positions/{ticket}/close", json=payload)
        return response if isinstance(response, dict) else {}

    def get_close_deal(self, ticket: int, deal: int | None = None) -> dict[str, Any]:
        params = {"deal": str(deal)} if deal is not None else None
        response = self._request("GET", f"/positions/{ticket}/close-deal", params=params)
        return response if isinstance(response, dict) else {}

    def modify_position_tp(self, ticket: int, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PATCH", f"/positions/{ticket}/tp", json=payload)
        return response if isinstance(response, dict) else {}

    def calculate_profit(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/profit-preview", json=payload)
        return response if isinstance(response, dict) else {}

    def get_rates(self, broker_symbol: str, timeframe: str = "D1", *, count: int = 120, start_pos: int = 1) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/rates/{broker_symbol}",
            params={"timeframe": timeframe, "count": count, "start_pos": start_pos},
        )
        return response if isinstance(response, list) else []

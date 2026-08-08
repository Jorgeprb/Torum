from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import logging
from threading import local
import time
from typing import Any

import requests

from bridge.config import BridgeSettings

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


class BackendClient:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self._local = local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            token = self.settings.torum_service_token.get_secret_value() if self.settings.torum_service_token else ""
            if token:
                session.headers.update({"X-Torum-Service-Token": token})
            self._local.session = session
        return session

    def health(self) -> bool:
        try:
            response = self._session().get(
                self._url(self.settings.torum_health_endpoint),
                timeout=self.settings.torum_http_timeout_seconds,
            )
            if response.status_code == 404 and self.settings.torum_health_endpoint != "/health":
                response = self._session().get(self._url("/health"), timeout=self.settings.torum_http_timeout_seconds)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning("Backend healthcheck failed: %s", exc)
            return False

    def get_symbols(self) -> list[dict[str, object]] | None:
        try:
            response = self._session().get(
                self._url(self.settings.torum_symbols_endpoint),
                timeout=self.settings.torum_http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            logger.warning("Unexpected symbols response from backend: %s", payload)
        except requests.RequestException as exc:
            logger.warning("Could not load symbols from backend: %s", exc)
        return None

    def post_ticks_batch(self, ticks: list[dict[str, Any]], account: dict[str, Any] | None, source: str = "MT5") -> dict[str, Any]:
        payload: dict[str, Any] = {"source": source, "ticks": ticks}
        if account is not None:
            payload["account"] = account
        return self._post_with_retries(self.settings.torum_ticks_batch_endpoint, payload)

    def post_status(self, status: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._post_with_retries(self.settings.torum_mt5_status_endpoint, status)
        except requests.RequestException as exc:
            logger.warning("Could not post MT5 bridge status: %s", exc)
            return None

    def post_positions_sync(
        self,
        positions: list[dict[str, Any]],
        account: dict[str, Any] | None,
        closed_deals: list[dict[str, Any]] | None = None,
        capital_flows: list[dict[str, Any]] | None = None,
        *,
        deals_checked: bool = False,
    ) -> dict[str, Any] | None:
        try:
            payload: dict[str, Any] = {"positions": positions}
            if closed_deals is not None:
                payload["closed_deals"] = closed_deals
            if capital_flows is not None:
                payload["capital_flows"] = capital_flows
            payload["deals_checked"] = bool(deals_checked)
            if account is not None:
                payload["account"] = account
            return self._post_with_retries(self.settings.torum_mt5_positions_sync_endpoint, payload)
        except requests.RequestException as exc:
            logger.warning("Could not post MT5 positions sync: %s", exc)
            return None

    def _post_with_retries(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: requests.RequestException | None = None
        for attempt in range(1, self.settings.torum_http_max_retries + 1):
            try:
                response = self._session().post(
                    self._url(endpoint),
                    json=_json_safe(payload),
                    timeout=self.settings.torum_http_timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("POST %s failed on attempt %s: %s", endpoint, attempt, exc)
                if attempt < self.settings.torum_http_max_retries:
                    time.sleep(min(2.0, 0.25 * attempt))
        assert last_error is not None
        raise last_error

    def _url(self, endpoint: str) -> str:
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{self.settings.api_base_url}{endpoint}"

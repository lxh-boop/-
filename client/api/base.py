from __future__ import annotations

import os
import threading
from typing import Any

import requests

from client.api.serialization import decode_transport, encode_transport


class ApiClientError(RuntimeError):
    def __init__(self, message: str, *, code: str = "API_ERROR", status_code: int = 0, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code or 0)
        self.details = details


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None) -> None:
        self.base_url = str(base_url or os.environ.get("STOCK_AGENT_API_URL") or "http://127.0.0.1:8010").rstrip("/")
        self.timeout_seconds = float(timeout_seconds or os.environ.get("STOCK_AGENT_API_TIMEOUT_SECONDS") or 600)
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
            self._local.session = session
        return session

    def health(self) -> dict[str, Any]:
        return self.get("/api/v1/health")

    def get(self, path: str) -> Any:
        try:
            response = self.session.get(self.base_url + path, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise ApiClientError(f"FastAPI service unavailable: {exc}", code="API_UNAVAILABLE") from exc
        return self._decode_response(response)

    def post(self, path: str, *, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:
        body = {
            "args": encode_transport(list(args or [])),
            "kwargs": encode_transport(dict(kwargs or {})),
        }
        try:
            response = self.session.post(self.base_url + path, json=body, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise ApiClientError(f"FastAPI service unavailable: {exc}", code="API_UNAVAILABLE") from exc
        return self._decode_response(response)

    @staticmethod
    def _decode_response(response: requests.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError(
                f"FastAPI returned non-JSON response ({response.status_code}).",
                code="INVALID_API_RESPONSE",
                status_code=response.status_code,
                details=response.text[-1000:],
            ) from exc
        if response.status_code >= 400 or not payload.get("success", False):
            error = payload.get("error") or {}
            raise ApiClientError(
                str(error.get("message") or f"FastAPI request failed ({response.status_code})"),
                code=str(error.get("code") or "API_REQUEST_FAILED"),
                status_code=response.status_code,
                details=decode_transport(error.get("details")),
            )
        return decode_transport(payload.get("data"))


api_client = ApiClient()


def call_operation(domain: str, operation: str, *args: Any, **kwargs: Any) -> Any:
    return api_client.post(f"/api/v1/{str(domain).strip('/')}/operations/{operation}", args=list(args), kwargs=kwargs)


def load_bootstrap(domain: str) -> dict[str, Any]:
    payload = api_client.get(f"/api/v1/{str(domain).strip('/')}/bootstrap")
    return dict(payload or {})

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from client.api.base import ApiClientError, api_client
from client.api.serialization import decode_transport, encode_transport

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


@dataclass(slots=True)
class TaskHandle:
    task_id: str

    def status(self) -> dict[str, Any]:
        return get_task(self.task_id)

    def cancel(self) -> dict[str, Any]:
        return cancel_task(self.task_id)

    def acknowledge(self) -> dict[str, Any]:
        return acknowledge_task(self.task_id)

    def events(self, *, after_sequence: int = 0) -> Iterator[dict[str, Any]]:
        return stream_task_events(self.task_id, after_sequence=after_sequence)

    def wait(
        self,
        *,
        timeout_seconds: float | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        for event in self.events():
            if on_event is not None:
                on_event(event)
            task = event.get("task") if isinstance(event, dict) else None
            if isinstance(task, dict) and task.get("status") in TERMINAL_STATUSES:
                return task
            if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                raise TimeoutError(f"Timed out waiting for task {self.task_id}")
        return self.status()


def _decode_response(response) -> Any:
    return api_client._decode_response(response)


def submit_task(
    task_type: str,
    *,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    owner_id: str = "",
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
    timeout_seconds: int = 600,
    max_retries: int = 0,
) -> TaskHandle:
    body = {
        "task_type": str(task_type),
        "args": encode_transport(list(args or [])),
        "kwargs": encode_transport(dict(kwargs or {})),
        "owner_id": str(owner_id or ""),
        "session_id": str(session_id or ""),
        "metadata": encode_transport(dict(metadata or {})),
        "timeout_seconds": max(1, int(timeout_seconds)),
        "max_retries": max(0, int(max_retries)),
    }
    try:
        response = api_client.session.post(api_client.base_url + "/api/v1/tasks", json=body, timeout=30)
    except Exception as exc:
        raise ApiClientError(f"FastAPI task service unavailable: {exc}", code="API_UNAVAILABLE") from exc
    task = _decode_response(response)
    return TaskHandle(str(task.get("task_id") or ""))


def get_task(task_id: str) -> dict[str, Any]:
    return dict(api_client.get(f"/api/v1/tasks/{task_id}") or {})


def list_tasks(**params: Any) -> list[dict[str, Any]]:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    try:
        response = api_client.session.get(api_client.base_url + "/api/v1/tasks", params=clean, timeout=30)
    except Exception as exc:
        raise ApiClientError(f"FastAPI task service unavailable: {exc}", code="API_UNAVAILABLE") from exc
    return list(_decode_response(response) or [])


def find_latest_task(
    *, owner_id: str = "", session_id: str = "", task_type: str = "",
    active_only: bool = False, unacknowledged_only: bool = False,
) -> dict[str, Any] | None:
    rows = list_tasks(
        owner_id=owner_id,
        session_id=session_id,
        task_type=task_type,
        active_only=active_only,
        unacknowledged_only=unacknowledged_only,
        limit=1,
    )
    return rows[0] if rows else None


def cancel_task(task_id: str) -> dict[str, Any]:
    return dict(api_client.post(f"/api/v1/tasks/{task_id}/cancel") or {})


def acknowledge_task(task_id: str) -> dict[str, Any]:
    return dict(api_client.post(f"/api/v1/tasks/{task_id}/acknowledge") or {})


def stream_task_events(task_id: str, *, after_sequence: int = 0) -> Iterator[dict[str, Any]]:
    headers = {"Accept": "text/event-stream"}
    if after_sequence:
        headers["Last-Event-ID"] = str(after_sequence)
    try:
        response = api_client.session.get(
            api_client.base_url + f"/api/v1/tasks/{task_id}/events",
            headers=headers,
            stream=True,
            timeout=(10, max(30, api_client.timeout_seconds)),
        )
        response.raise_for_status()
    except Exception as exc:
        raise ApiClientError(f"Task event stream unavailable: {exc}", code="SSE_UNAVAILABLE") from exc
    event_name = "message"
    data_lines: list[str] = []
    for raw in response.iter_lines(decode_unicode=True):
        line = raw or ""
        if not line:
            if data_lines:
                payload = decode_transport(json.loads("\n".join(data_lines)))
                if event_name == "task-complete" and isinstance(payload, dict):
                    yield dict(payload)
                else:
                    yield dict(payload or {})
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

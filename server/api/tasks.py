from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.api.contracts import OperationResponse
from server.api.dispatch import llm_settings_registry
from server.api.serialization import decode_transport, encode_transport
from server.task_runtime.manager import TaskManager
from server.task_runtime.store import TERMINAL_STATUSES

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
task_manager = TaskManager()


class TaskSubmitRequest(BaseModel):
    task_type: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    owner_id: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 600
    max_retries: int = 0


def _success(data: Any) -> OperationResponse:
    return OperationResponse(success=True, data=encode_transport(data), request_id=uuid.uuid4().hex)


def _failure(exc: Exception) -> OperationResponse:
    return OperationResponse(
        success=False,
        error={"code": type(exc).__name__, "message": str(exc), "details": {}},
        request_id=uuid.uuid4().hex,
    )


@router.post("", response_model=OperationResponse)
def submit_task(request: TaskSubmitRequest) -> OperationResponse:
    args = list(decode_transport(request.args) or [])
    kwargs = dict(decode_transport(request.kwargs) or {})
    secrets: dict[str, str] = {}
    if request.task_type == "agent.run":
        settings_payload = kwargs.pop("llm_settings", None)
        if settings_payload:
            settings = llm_settings_registry.resolve(settings_payload)
            kwargs["llm_settings_descriptor"] = {
                "profile_id": str(settings.profile_id),
                "mode": str(settings.mode),
                "provider": str(settings.provider),
                "base_url": str(settings.base_url),
                "model": str(settings.model),
                "disable_thinking": bool(settings.disable_thinking),
                "request_timeout_seconds": int(settings.request_timeout_seconds),
                "max_retries": int(settings.max_retries),
            }
            secrets["llm_credential"] = str(getattr(settings, "credential", "") or "")
    try:
        task = task_manager.submit(
            task_type=request.task_type,
            args=args,
            kwargs=kwargs,
            owner_id=request.owner_id,
            session_id=request.session_id,
            metadata=decode_transport(request.metadata) or {},
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            secrets=secrets,
        )
        return _success(task)
    except Exception as exc:
        return _failure(exc)


@router.get("", response_model=OperationResponse)
def list_tasks(
    owner_id: str = "",
    session_id: str = "",
    task_type: str = "",
    active_only: bool = False,
    unacknowledged_only: bool = False,
    limit: int = 20,
) -> OperationResponse:
    try:
        return _success(task_manager.store.list(
            owner_id=owner_id,
            session_id=session_id,
            task_type=task_type,
            active_only=active_only,
            unacknowledged_only=unacknowledged_only,
            limit=limit,
        ))
    except Exception as exc:
        return _failure(exc)


@router.get("/{task_id}", response_model=OperationResponse)
def get_task(task_id: str) -> OperationResponse:
    try:
        return _success(task_manager.store.get(task_id))
    except Exception as exc:
        return _failure(exc)


@router.post("/{task_id}/cancel", response_model=OperationResponse)
def cancel_task(task_id: str) -> OperationResponse:
    try:
        return _success(task_manager.cancel(task_id))
    except Exception as exc:
        return _failure(exc)


@router.post("/{task_id}/acknowledge", response_model=OperationResponse)
def acknowledge_task(task_id: str) -> OperationResponse:
    try:
        return _success(task_manager.store.acknowledge(task_id))
    except Exception as exc:
        return _failure(exc)


@router.get("/{task_id}/events")
def task_events(
    task_id: str,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    start_after = max(after, int(last_event_id or 0))
    task_manager.store.get(task_id)

    def stream():
        sequence = start_after
        idle = 0
        while True:
            events = task_manager.store.events(task_id, after_sequence=sequence, limit=200)
            for event in events:
                sequence = int(event["sequence"])
                payload = json.dumps(encode_transport(event), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {sequence}\nevent: task-event\ndata: {payload}\n\n"
            task = task_manager.store.get(task_id)
            if task["status"] in TERMINAL_STATUSES and not events:
                payload = json.dumps(encode_transport({"task": task}), ensure_ascii=False, separators=(",", ":"))
                yield f"event: task-complete\ndata: {payload}\n\n"
                break
            idle += 1
            if idle % 10 == 0:
                yield ": heartbeat\n\n"
            time.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

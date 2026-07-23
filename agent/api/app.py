from __future__ import annotations

import json
import logging
import os
import time
import hmac
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .config import AgentApiSettings
from .models import ApiEnvelope, ChatRequest
from .service import AgentApiError, AgentExecutionService


logger = logging.getLogger("agent.api")


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.getenv("AGENT_API_LOG_LEVEL", "INFO").upper(),
        format="%(message)s",
    )


def _event(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def create_app(settings: AgentApiSettings | None = None) -> FastAPI:
    _configure_logging()
    cfg = settings or AgentApiSettings.from_env()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    service = AgentExecutionService.build(cfg)
    app = FastAPI(
        title="Stock Daily Multi-Agent API",
        version="2.0.0",
        description="Stable HTTP/SSE/WebSocket entry for the single Main Coordinator Agent.",
    )
    app.state.settings = cfg
    app.state.agent_service = service

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID", "X-API-Key"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:12]}"
        request.state.request_id = request_id
        started = time.perf_counter()
        if request.url.path.startswith("/v1/") and cfg.api_key:
            supplied = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(supplied, cfg.api_key):
                response = JSONResponse(
                    status_code=401,
                    content=ApiEnvelope(
                        request_id=request_id,
                        status="error",
                        error={"code": "unauthorized", "message": "Invalid API key.", "retryable": False},
                    ).model_dump(),
                )
                response.headers["X-Request-ID"] = request_id
                return response
        try:
            response = await call_next(request)
        except AgentApiError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content=ApiEnvelope(
                    request_id=request_id,
                    status="error",
                    error={
                        "code": exc.code,
                        "message": exc.public_message,
                        "retryable": exc.retryable,
                    },
                ).model_dump(),
            )
        response.headers["X-Request-ID"] = request_id
        _event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )
        return response

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        output_ready = cfg.output_dir.exists() and os.access(cfg.output_dir, os.W_OK)
        payload = {
            "status": "ok" if output_ready else "not_ready",
            "checks": {
                "output_dir_writable": output_ready,
                "single_main_agent_entry": True,
                "max_concurrency": cfg.max_concurrency,
                "distributed_rate_limit": bool(cfg.redis_url),
                "api_key_auth_enabled": bool(cfg.api_key),
            },
        }
        return JSONResponse(status_code=200 if output_ready else 503, content=payload)

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(service.metrics.prometheus_text(), media_type="text/plain; version=0.0.4")

    @app.post("/v1/agent/chat")
    async def chat(payload: ChatRequest, request: Request) -> JSONResponse:
        request_id = request.state.request_id
        client_host = request.client.host if request.client else "unknown"
        await service.check_rate_limit(f"{payload.user_id}:{client_host}")
        started = time.perf_counter()
        result = await service.execute(payload, request_id=request_id)
        envelope = ApiEnvelope(
            request_id=request_id,
            status="ok",
            data=result,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )
        return JSONResponse(content=envelope.model_dump())

    @app.post("/v1/agent/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        request_id = request.state.request_id
        client_host = request.client.host if request.client else "unknown"
        await service.check_rate_limit(f"{payload.user_id}:{client_host}")

        async def generate():
            def sse(event: str, data: dict[str, object]) -> str:
                return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

            yield sse("accepted", {"request_id": request_id, "status": "accepted"})
            yield sse("progress", {"request_id": request_id, "stage": "main_coordinator_running"})
            try:
                result = await service.execute(payload, request_id=request_id)
                yield sse("result", {"request_id": request_id, "data": result})
            except AgentApiError as exc:
                yield sse(
                    "error",
                    {
                        "request_id": request_id,
                        "error": {
                            "code": exc.code,
                            "message": exc.public_message,
                            "retryable": exc.retryable,
                        },
                    },
                )

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.websocket("/v1/agent/ws")
    async def websocket_chat(websocket: WebSocket) -> None:
        if cfg.api_key and not hmac.compare_digest(websocket.headers.get("X-API-Key", ""), cfg.api_key):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_json()
                payload = ChatRequest.model_validate(raw)
                client_host = websocket.client.host if websocket.client else "unknown"
                await service.check_rate_limit(f"{payload.user_id}:{client_host}")
                request_id = f"req_{uuid4().hex[:12]}"
                await websocket.send_json({"event": "accepted", "request_id": request_id})
                result = await service.execute(payload, request_id=request_id)
                await websocket.send_json({"event": "result", "request_id": request_id, "data": result})
        except WebSocketDisconnect:
            return
        except AgentApiError as exc:
            await websocket.send_json(
                {
                    "event": "error",
                    "error": {"code": exc.code, "message": exc.public_message, "retryable": exc.retryable},
                }
            )
            await websocket.close(code=1013 if exc.retryable else 1011)
        except Exception:
            await websocket.send_json(
                {"event": "error", "error": {"code": "invalid_request", "message": "Invalid WebSocket request."}}
            )
            await websocket.close(code=1008)

    return app


app = create_app()

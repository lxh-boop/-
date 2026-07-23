from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .config import AgentApiSettings
from .metrics import ApiMetrics
from .models import ChatRequest
from .rate_limit import RateLimitBackend, build_rate_limiter


logger = logging.getLogger("agent.api")


class AgentApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 500, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = int(status_code)
        self.retryable = bool(retryable)


def _run_agent_request(payload: ChatRequest, settings: AgentApiSettings) -> dict[str, Any]:
    # Lazy import keeps health checks and API startup independent from heavy model/RAG imports.
    from agent.executor import run_agent_request

    return run_agent_request(
        query=payload.query,
        user_id=payload.user_id,
        output_dir=settings.output_dir,
        db_path=settings.db_path or None,
        top_k=payload.top_k or settings.default_top_k,
        session_id=payload.session_id,
        reply_language=payload.reply_language,
        llm_mode=payload.llm_mode,
        decomposition_context=dict(payload.decomposition_context or {}),
    )


@dataclass
class AgentExecutionService:
    settings: AgentApiSettings
    metrics: ApiMetrics
    limiter: RateLimitBackend

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)

    @classmethod
    def build(cls, settings: AgentApiSettings) -> "AgentExecutionService":
        return cls(
            settings=settings,
            metrics=ApiMetrics(),
            limiter=build_rate_limiter(settings.redis_url),
        )

    async def check_rate_limit(self, key: str) -> None:
        decision = await self.limiter.allow(
            key,
            limit=self.settings.rate_limit_requests,
            window_seconds=self.settings.rate_limit_window_seconds,
        )
        if not decision.allowed:
            raise AgentApiError(
                "rate_limited",
                "Too many requests. Please retry later.",
                status_code=429,
                retryable=True,
            )

    async def execute(self, payload: ChatRequest, *, request_id: str | None = None) -> dict[str, Any]:
        request_id = request_id or f"req_{uuid4().hex[:12]}"
        started = time.perf_counter()
        self.metrics.started()
        status = "error"
        try:
            async with self._semaphore:
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(_run_agent_request, payload, self.settings),
                        timeout=self.settings.request_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    raise AgentApiError(
                        "request_timeout",
                        "Agent execution timed out. The request was not retried automatically.",
                        status_code=504,
                        retryable=True,
                    ) from exc
                except AgentApiError:
                    raise
                except Exception as exc:
                    logger.exception(
                        "agent_execution_failed",
                        extra={"request_id": request_id, "error_type": type(exc).__name__},
                    )
                    raise AgentApiError(
                        "agent_execution_failed",
                        "The Agent service could not complete this request.",
                        status_code=500,
                        retryable=False,
                    ) from exc
            status = "ok" if bool(result.get("success")) else "business_error"
            return result
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.finished(route="chat", status=status, elapsed_ms=elapsed_ms)

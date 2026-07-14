from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from statistics import mean, median
from typing import Any, Callable, Generic, TypeVar
from uuid import uuid4

from database.repositories import AgentRepository


T = TypeVar("T")


ERROR_TIMEOUT = "timeout"
ERROR_TRANSIENT = "transient"
ERROR_VALIDATION = "validation"
ERROR_PERMISSION = "permission"
ERROR_DEPENDENCY = "dependency"
ERROR_BUSINESS_STATE_CHANGED = "business_state_changed"
ERROR_BUDGET_EXCEEDED = "budget_exceeded"
ERROR_INTERNAL = "internal"

RECOVERABLE_ERROR_TYPES = {ERROR_TIMEOUT, ERROR_TRANSIENT, ERROR_DEPENDENCY}
NON_RETRYABLE_ERROR_TYPES = {
    ERROR_VALIDATION,
    ERROR_PERMISSION,
    ERROR_BUSINESS_STATE_CHANGED,
    ERROR_BUDGET_EXCEEDED,
    ERROR_INTERNAL,
}
CHECKPOINT_SAFE_STATUSES = {
    "planning",
    "running",
    "observing",
    "replanning",
    "waiting_for_approval",
    "revalidating",
    "partially_completed",
}
CHECKPOINT_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "expired",
}
SENSITIVE_CHECKPOINT_KEYS = {
    "api_key",
    "token",
    "confirmation_token",
    "confirmation_token_hash",
    "llm_api_key",
    "tushare_token",
    "password",
    "secret",
}


class RuntimeTimeoutError(TimeoutError):
    pass


class RuntimeBudgetExceeded(RuntimeError):
    pass


class RuntimeCircuitOpen(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimePolicy:
    agent_timeout_seconds: float = 60.0
    tool_timeout_seconds: float = 30.0
    max_retry_attempts: int = 2
    retry_backoff_seconds: float = 0.05
    max_run_steps: int = 30
    max_replan_count: int = 2
    max_tool_calls: int = 40
    soft_token_budget: int = 12000
    hard_token_budget: int = 16000
    soft_llm_call_budget: int = 6
    hard_llm_call_budget: int = 8
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    recoverable_error_types: set[str] = field(default_factory=lambda: set(RECOVERABLE_ERROR_TYPES))
    non_retryable_error_types: set[str] = field(default_factory=lambda: set(NON_RETRYABLE_ERROR_TYPES))
    tool_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "RuntimePolicy":
        # The local multilingual dense model and Cross-Encoder can take longer
        # than the generic tool budget on their first, cold process load. Keep
        # the larger budget scoped to read-only RAG tools and avoid retrying the
        # same CPU-heavy initialization after a timeout.
        rag_cold_start = {
            "tool_timeout_seconds": 90.0,
            "max_retry_attempts": 1,
        }
        return cls(
            tool_overrides={
                "stock_rag": dict(rag_cold_start),
                "evidence.search_rag": dict(rag_cold_start),
            }
        )

    def resolve_for_tool(self, tool_name: str) -> "RuntimePolicy":
        return self._resolve(self.tool_overrides.get(str(tool_name or ""), {}))

    def resolve_for_agent(self, agent_name: str) -> "RuntimePolicy":
        return self._resolve(self.agent_overrides.get(str(agent_name or ""), {}))

    def _resolve(self, overrides: dict[str, Any]) -> "RuntimePolicy":
        if not overrides:
            return self
        allowed = set(self.__dataclass_fields__) - {"tool_overrides", "agent_overrides"}
        changes = {key: value for key, value in overrides.items() if key in allowed}
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["recoverable_error_types"] = sorted(self.recoverable_error_types)
        data["non_retryable_error_types"] = sorted(self.non_retryable_error_types)
        return data


@dataclass
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.05
    retry_read_only_only: bool = True


@dataclass
class RuntimeAttempt:
    attempt: int
    error_type: str
    elapsed_ms: float
    retryable: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeCallMetadata:
    tool_name: str
    attempt_count: int
    retry_count: int
    elapsed_ms: float
    timeout_ms: int
    retryable: bool
    error_type: str
    circuit_state: str
    attempts: list[dict[str, Any]]
    budget_usage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeBudget:
    """Track independent runtime budgets.

    ``token_estimate`` is reserved for real LLM traffic. Tool argument size is
    tracked separately in ``tool_payload_estimate`` and never blocks a local,
    deterministic tool. This prevents a large in-memory payload from being
    mistaken for paid model tokens.
    """

    policy: RuntimePolicy = field(default_factory=RuntimePolicy.default)
    tool_calls: int = 0
    llm_calls: int = 0
    token_estimate: int = 0
    tool_payload_estimate: int = 0
    started_at: float = field(default_factory=time.monotonic)
    soft_budget_triggered: bool = False
    hard_budget_triggered: bool = False
    soft_tool_budget_triggered: bool = False
    hard_tool_budget_triggered: bool = False
    soft_llm_budget_triggered: bool = False
    hard_llm_budget_triggered: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record_tool_call(
        self,
        *,
        token_estimate: int = 0,
        payload_estimate: int | None = None,
    ) -> None:
        """Record a tool call without charging its payload as LLM tokens.

        ``token_estimate`` remains accepted for backward compatibility with
        older callers. It is interpreted as a tool payload estimate only.
        """
        payload = token_estimate if payload_estimate is None else payload_estimate
        with self._lock:
            self.tool_calls += 1
            self.tool_payload_estimate += max(0, int(payload or 0))
            self._refresh_flags_unlocked()

    def record_llm_call(self, *, token_estimate: int = 0) -> None:
        with self._lock:
            self.llm_calls += 1
            self.token_estimate += max(0, int(token_estimate or 0))
            self._refresh_flags_unlocked()

    def ensure_can_start_tool(self) -> None:
        """Guard only the tool-call budget.

        An exhausted LLM budget must not block deterministic Python tools that
        can finish the user's request with data already in memory.
        """
        with self._lock:
            self._refresh_flags_unlocked()
            if self.tool_calls >= int(self.policy.max_tool_calls):
                self.hard_tool_budget_triggered = True
                self.hard_budget_triggered = True
                raise RuntimeBudgetExceeded("budget_exceeded:max_tool_calls")

    def ensure_can_start_llm(self, *, additional_tokens: int = 0) -> None:
        """Guard a paid model call using only actual/estimated LLM usage."""
        additional = max(0, int(additional_tokens or 0))
        with self._lock:
            self._refresh_flags_unlocked()
            if self.llm_calls >= int(self.policy.hard_llm_call_budget):
                self.hard_llm_budget_triggered = True
                self.hard_budget_triggered = True
                raise RuntimeBudgetExceeded("budget_exceeded:hard_llm_call_budget")
            if self.token_estimate + additional > int(self.policy.hard_token_budget):
                self.hard_llm_budget_triggered = True
                self.hard_budget_triggered = True
                raise RuntimeBudgetExceeded("budget_exceeded:hard_token_budget")

    @property
    def tool_budget_exhausted(self) -> bool:
        with self._lock:
            self._refresh_flags_unlocked()
            return self.hard_tool_budget_triggered

    @property
    def llm_budget_exhausted(self) -> bool:
        with self._lock:
            self._refresh_flags_unlocked()
            return self.hard_llm_budget_triggered

    def should_reduce_optional_work(self) -> bool:
        with self._lock:
            self._refresh_flags_unlocked()
            return self.soft_budget_triggered

    def _refresh_flags_unlocked(self) -> None:
        self.soft_tool_budget_triggered = (
            self.tool_calls >= max(1, int(self.policy.max_tool_calls * 0.8))
        )
        self.hard_tool_budget_triggered = (
            self.tool_calls >= int(self.policy.max_tool_calls)
        )
        self.soft_llm_budget_triggered = (
            self.token_estimate >= int(self.policy.soft_token_budget)
            or self.llm_calls >= int(self.policy.soft_llm_call_budget)
        )
        self.hard_llm_budget_triggered = (
            self.token_estimate >= int(self.policy.hard_token_budget)
            or self.llm_calls >= int(self.policy.hard_llm_call_budget)
        )
        self.soft_budget_triggered = (
            self.soft_tool_budget_triggered or self.soft_llm_budget_triggered
        )
        self.hard_budget_triggered = (
            self.hard_tool_budget_triggered or self.hard_llm_budget_triggered
        )

    def _refresh_flags(self) -> None:
        with self._lock:
            self._refresh_flags_unlocked()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_flags_unlocked()
            elapsed_ms = (time.monotonic() - self.started_at) * 1000.0
            return {
                "tool_calls": self.tool_calls,
                "llm_calls": self.llm_calls,
                "token_estimate": self.token_estimate,
                "llm_token_estimate": self.token_estimate,
                "tool_payload_estimate": self.tool_payload_estimate,
                "elapsed_ms": round(elapsed_ms, 3),
                "soft_budget_triggered": self.soft_budget_triggered,
                "hard_budget_triggered": self.hard_budget_triggered,
                "soft_tool_budget_triggered": self.soft_tool_budget_triggered,
                "hard_tool_budget_triggered": self.hard_tool_budget_triggered,
                "soft_llm_budget_triggered": self.soft_llm_budget_triggered,
                "hard_llm_budget_triggered": self.hard_llm_budget_triggered,
                "max_tool_calls": self.policy.max_tool_calls,
                "soft_token_budget": self.policy.soft_token_budget,
                "hard_token_budget": self.policy.hard_token_budget,
                "soft_llm_call_budget": self.policy.soft_llm_call_budget,
                "hard_llm_call_budget": self.policy.hard_llm_call_budget,
            }


@dataclass
class CancellationToken:
    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "") -> None:
        self.cancelled = True
        self.reason = reason

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError(f"runtime_cancelled:{self.reason}")


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failure_count: int = 0
    opened_at: float = 0.0
    half_open_probe: bool = False

    def allow_request(self) -> bool:
        if self.failure_count < self.failure_threshold:
            return True
        if (time.monotonic() - self.opened_at) >= self.recovery_seconds:
            self.half_open_probe = True
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = 0.0
        self.half_open_probe = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.half_open_probe = False
        if self.failure_count >= self.failure_threshold:
            self.opened_at = time.monotonic()

    @property
    def state(self) -> str:
        if self.failure_count < self.failure_threshold:
            return "closed"
        if (time.monotonic() - self.opened_at) >= self.recovery_seconds:
            return "half_open"
        return "open"


class CircuitBreakerRegistry:
    def __init__(self, policy: RuntimePolicy | None = None) -> None:
        self.policy = policy or RuntimePolicy.default()
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, tool_name: str) -> CircuitBreaker:
        key = str(tool_name or "unknown")
        if key not in self._breakers:
            policy = self.policy.resolve_for_tool(key)
            self._breakers[key] = CircuitBreaker(
                failure_threshold=int(policy.circuit_failure_threshold),
                recovery_seconds=float(policy.circuit_recovery_seconds),
            )
        return self._breakers[key]

    def state(self, tool_name: str) -> str:
        return self.get(tool_name).state

    def snapshot(self) -> dict[str, str]:
        return {tool_name: breaker.state for tool_name, breaker in self._breakers.items()}


@dataclass
class LatencyTracker:
    values: list[float] = field(default_factory=list)

    def record(self, seconds: float) -> None:
        self.values.append(max(0.0, float(seconds)))

    def summary(self) -> dict[str, float]:
        if not self.values:
            return {"count": 0, "average": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(self.values)
        p95_index = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
        return {
            "count": float(len(ordered)),
            "average": mean(ordered),
            "p50": median(ordered),
            "p95": ordered[p95_index],
            "max": ordered[-1],
        }


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_message(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def classify_runtime_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, (TimeoutError, RuntimeTimeoutError)):
        return ERROR_TIMEOUT
    if isinstance(exc, RuntimeBudgetExceeded) or "budget_exceeded" in text:
        return ERROR_BUDGET_EXCEEDED
    if isinstance(exc, PermissionError) or "permission" in text or "denied" in text:
        return ERROR_PERMISSION
    if isinstance(exc, (TypeError, ValueError)) or "invalid" in text or "missing_required" in text:
        return ERROR_VALIDATION
    if "business_state_changed" in text or "state_changed" in text or "stale" in text:
        return ERROR_BUSINESS_STATE_CHANGED
    if "dependency" in text or "database is locked" in text or "database is busy" in text:
        return ERROR_DEPENDENCY
    if any(marker in text for marker in ["temporary", "transient", "connection", "429", "rate limit", "busy"]):
        return ERROR_TRANSIENT
    return ERROR_INTERNAL


def is_retryable_runtime_error(
    exc: BaseException,
    *,
    read_only: bool,
    policy: RuntimePolicy | None = None,
) -> bool:
    if not read_only:
        return False
    resolved = policy or RuntimePolicy.default()
    return classify_runtime_error(exc) in resolved.recoverable_error_types


def run_with_timeout(operation: Callable[[], T], *, timeout_seconds: float, cancellation: CancellationToken | None = None) -> T:
    if cancellation:
        cancellation.raise_if_cancelled()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(operation)
    try:
        result = future.result(timeout=timeout_seconds)
    except FutureTimeout as exc:
        future.cancel()
        raise RuntimeTimeoutError(f"runtime_timeout:{timeout_seconds}") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if cancellation:
        cancellation.raise_if_cancelled()
    return result


def run_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    read_only: bool = True,
    retryable: Callable[[BaseException], bool] | None = None,
    cancellation: CancellationToken | None = None,
    attempt_recorder: Callable[[dict[str, Any]], None] | None = None,
) -> T:
    policy = policy or RetryPolicy()
    if policy.retry_read_only_only and not read_only:
        return operation()
    last_error: BaseException | None = None
    for attempt in range(max(1, int(policy.max_attempts))):
        if cancellation:
            cancellation.raise_if_cancelled()
        started = time.perf_counter()
        try:
            return operation()
        except BaseException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            can_retry = retryable(exc) if retryable else True
            if attempt_recorder:
                attempt_recorder(
                    RuntimeAttempt(
                        attempt=attempt + 1,
                        error_type=classify_runtime_error(exc),
                        elapsed_ms=round(elapsed_ms, 3),
                        retryable=bool(can_retry and attempt < policy.max_attempts - 1),
                        message=_safe_message(exc),
                    ).to_dict()
                )
            if not can_retry:
                raise
            if attempt >= policy.max_attempts - 1:
                raise
            last_error = exc
            time.sleep(policy.base_delay_seconds * (2 ** attempt))
    raise RuntimeError(f"runtime_retry_exhausted:{last_error}")


def execute_with_policy(
    operation: Callable[[], T],
    *,
    tool_name: str,
    read_only: bool,
    policy: RuntimePolicy | None = None,
    budget: RuntimeBudget | None = None,
    circuit_registry: CircuitBreakerRegistry | None = None,
    cancellation: CancellationToken | None = None,
    token_estimate: int = 0,
    tool_payload_estimate: int | None = None,
) -> tuple[T, RuntimeCallMetadata]:
    resolved = (policy or RuntimePolicy.default()).resolve_for_tool(tool_name)
    budget = budget or RuntimeBudget(resolved)
    circuit_registry = circuit_registry or CircuitBreakerRegistry(resolved)
    breaker = circuit_registry.get(tool_name)
    circuit_state_before = breaker.state
    if not breaker.allow_request():
        raise RuntimeCircuitOpen(f"circuit_open:{tool_name}")
    budget.ensure_can_start_tool()

    attempts: list[dict[str, Any]] = []
    started_all = time.perf_counter()

    def wrapped() -> T:
        return run_with_timeout(
            operation,
            timeout_seconds=float(resolved.tool_timeout_seconds),
            cancellation=cancellation,
        )

    try:
        result = run_with_retry(
            wrapped,
            policy=RetryPolicy(
                max_attempts=max(1, int(resolved.max_retry_attempts)),
                base_delay_seconds=float(resolved.retry_backoff_seconds),
                retry_read_only_only=True,
            ),
            read_only=read_only,
            retryable=lambda exc: is_retryable_runtime_error(exc, read_only=read_only, policy=resolved),
            cancellation=cancellation,
            attempt_recorder=attempts.append,
        )
        budget.record_tool_call(token_estimate=token_estimate, payload_estimate=tool_payload_estimate)
        breaker.record_success()
        elapsed_ms = (time.perf_counter() - started_all) * 1000.0
        metadata = RuntimeCallMetadata(
            tool_name=tool_name,
            attempt_count=max(1, len(attempts) + 1),
            retry_count=len(attempts),
            elapsed_ms=round(elapsed_ms, 3),
            timeout_ms=int(float(resolved.tool_timeout_seconds) * 1000),
            retryable=False,
            error_type="",
            circuit_state=breaker.state,
            attempts=attempts,
            budget_usage=budget.to_dict(),
        )
        return result, metadata
    except BaseException as exc:
        error_type = classify_runtime_error(exc)
        if error_type in {ERROR_TIMEOUT, ERROR_TRANSIENT, ERROR_DEPENDENCY, ERROR_INTERNAL}:
            breaker.record_failure()
        budget.record_tool_call(token_estimate=token_estimate, payload_estimate=tool_payload_estimate)
        elapsed_ms = (time.perf_counter() - started_all) * 1000.0
        if not attempts:
            attempts.append(
                RuntimeAttempt(
                    attempt=1,
                    error_type=error_type,
                    elapsed_ms=round(elapsed_ms, 3),
                    retryable=False,
                    message=_safe_message(exc),
                ).to_dict()
            )
        exc.runtime_metadata = RuntimeCallMetadata(
            tool_name=tool_name,
            attempt_count=len(attempts),
            retry_count=max(0, len(attempts) - 1),
            elapsed_ms=round(elapsed_ms, 3),
            timeout_ms=int(float(resolved.tool_timeout_seconds) * 1000),
            retryable=is_retryable_runtime_error(exc, read_only=read_only, policy=resolved),
            error_type=error_type,
            circuit_state=breaker.state if circuit_state_before != "open" else "open",
            attempts=attempts,
            budget_usage=budget.to_dict(),
        ).to_dict()
        raise


def summarize_large_output(value: object, *, max_chars: int = 2000) -> dict[str, object]:
    text = str(value)
    return {
        "truncated": len(text) > max_chars,
        "original_length": len(text),
        "preview": text[:max_chars],
    }


def _redact_checkpoint_payload(value: Any, *, max_chars: int = 800) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key.lower() in SENSITIVE_CHECKPOINT_KEYS or any(marker in text_key.lower() for marker in ["token", "secret", "password", "api_key"]):
                out[text_key] = "***"
            else:
                out[text_key] = _redact_checkpoint_payload(item, max_chars=max_chars)
        return out
    if isinstance(value, list):
        items = [_redact_checkpoint_payload(item, max_chars=max_chars) for item in value[:20]]
        if len(value) > 20:
            items.append({"truncated_count": len(value) - 20})
        return items
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "...[truncated]"
    return value


class RuntimeCheckpointer:
    def __init__(self, db_path: str | None = None) -> None:
        self.repo = AgentRepository(db_path)

    def save(
        self,
        *,
        run_id: str,
        stage: str,
        completed_steps: list[str] | None = None,
        pending_tasks: list[dict[str, Any]] | None = None,
        references: dict[str, Any] | None = None,
        write_intent: bool = False,
    ) -> dict[str, Any]:
        row = self.repo._decode_runtime_record(
            "agent_runs",
            self.repo.store.get("agent_runs", {"run_id": run_id}),
        ) or {}
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
        metadata = dict(metadata or {})
        checkpoint = {
            "checkpoint_id": f"checkpoint_{uuid4().hex[:12]}",
            "run_id": run_id,
            "stage": str(stage or ""),
            "created_at": _now_text(),
            "completed_steps": list(completed_steps or []),
            "pending_tasks": _redact_checkpoint_payload(list(pending_tasks or [])),
            "references": _redact_checkpoint_payload(dict(references or {})),
            "write_intent": bool(write_intent),
            "resume_entrypoint": "revalidate" if write_intent or str(stage) in {"waiting_for_approval", "revalidating", "committing"} else "readonly_resume",
        }
        checkpoints = list(metadata.get("checkpoints") or [])
        checkpoints.append(checkpoint)
        metadata["checkpoints"] = checkpoints[-20:]
        metadata["latest_checkpoint_id"] = checkpoint["checkpoint_id"]
        metadata["recovery_lock"] = metadata.get("recovery_lock") or None
        self.repo.upsert_agent_run(
            {
                "run_id": run_id,
                "conversation_id": row.get("conversation_id"),
                "user_id": row.get("user_id") or "default",
                "goal": row.get("goal") or "",
                "status": row.get("status") or stage,
                "metadata": metadata,
            }
        )
        return checkpoint

    def latest(self, run_id: str) -> dict[str, Any]:
        row = self.repo._decode_runtime_record(
            "agent_runs",
            self.repo.store.get("agent_runs", {"run_id": run_id}),
        ) or {}
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
        checkpoints = list((metadata or {}).get("checkpoints") or [])
        return checkpoints[-1] if checkpoints else {}

    def acquire_recovery_lock(self, run_id: str, owner: str | None = None) -> bool:
        row = self.repo._decode_runtime_record(
            "agent_runs",
            self.repo.store.get("agent_runs", {"run_id": run_id}),
        ) or {}
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
        metadata = dict(metadata or {})
        if metadata.get("recovery_lock"):
            return False
        metadata["recovery_lock"] = {"owner": owner or f"recovery_{uuid4().hex[:8]}", "acquired_at": _now_text()}
        self.repo.upsert_agent_run(
            {
                "run_id": run_id,
                "conversation_id": row.get("conversation_id"),
                "user_id": row.get("user_id") or "default",
                "goal": row.get("goal") or "",
                "status": row.get("status") or "running",
                "metadata": metadata,
            }
        )
        return True

    def release_recovery_lock(self, run_id: str) -> None:
        row = self.repo._decode_runtime_record(
            "agent_runs",
            self.repo.store.get("agent_runs", {"run_id": run_id}),
        ) or {}
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
        metadata = dict(metadata or {})
        metadata["recovery_lock"] = None
        self.repo.upsert_agent_run(
            {
                "run_id": run_id,
                "conversation_id": row.get("conversation_id"),
                "user_id": row.get("user_id") or "default",
                "goal": row.get("goal") or "",
                "status": row.get("status") or "running",
                "metadata": metadata,
            }
        )


_RECOVERY_LOCKS: dict[str, threading.Lock] = {}


def recover_run_from_checkpoint(
    *,
    run_id: str,
    db_path: str | None = None,
    allow_write_resume: bool = False,
) -> dict[str, Any]:
    lock = _RECOVERY_LOCKS.setdefault(run_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return {"success": False, "run_id": run_id, "error_type": "recovery_already_running"}
    checkpointer = RuntimeCheckpointer(db_path)
    acquired = False
    try:
        acquired = checkpointer.acquire_recovery_lock(run_id)
        if not acquired:
            return {"success": False, "run_id": run_id, "error_type": "recovery_already_running"}
        repo = AgentRepository(db_path)
        row = repo._decode_runtime_record("agent_runs", repo.store.get("agent_runs", {"run_id": run_id})) or {}
        status = str(row.get("status") or "")
        if status in CHECKPOINT_TERMINAL_STATUSES:
            return {"success": False, "run_id": run_id, "error_type": "terminal_run_not_resumable", "status": status}
        checkpoint = checkpointer.latest(run_id)
        if not checkpoint:
            return {"success": False, "run_id": run_id, "error_type": "missing_checkpoint"}
        entrypoint = str(checkpoint.get("resume_entrypoint") or "readonly_resume")
        if entrypoint == "revalidate" and not allow_write_resume:
            return {
                "success": True,
                "run_id": run_id,
                "resume_entrypoint": "revalidate",
                "checkpoint_id": checkpoint.get("checkpoint_id"),
                "message": "write run restored to revalidation entrypoint; commit is not resumed automatically",
            }
        return {
            "success": True,
            "run_id": run_id,
            "resume_entrypoint": entrypoint,
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "completed_steps": checkpoint.get("completed_steps") or [],
            "pending_tasks": checkpoint.get("pending_tasks") or [],
        }
    finally:
        if acquired:
            checkpointer.release_recovery_lock(run_id)
        lock.release()


def collect_runtime_health_summary(db_path: str | None = None) -> dict[str, Any]:
    repo = AgentRepository(db_path)
    try:
        runs = repo._list_runtime("agent_runs", filters={}, order_by="created_at", limit=500)
    except Exception:
        runs = []
    try:
        tool_calls = repo._list_runtime("agent_tool_calls", filters={}, order_by="started_at", limit=1000)
    except Exception:
        tool_calls = []

    run_count = len(runs)
    completed = sum(1 for row in runs if str(row.get("status") or "") in {"completed", "partially_completed"})
    failed = sum(1 for row in runs if str(row.get("status") or "") == "failed")
    durations = []
    retry_count = 0
    timeout_count = 0
    over_budget_count = 0
    circuit_states: dict[str, int] = {}
    resumable_runs = 0
    for row in runs:
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
        metadata = dict(metadata or {})
        health = metadata.get("runtime_health") if isinstance(metadata.get("runtime_health"), dict) else {}
        budget = metadata.get("budget_usage") if isinstance(metadata.get("budget_usage"), dict) else {}
        over_budget_count += int(bool(budget.get("soft_budget_triggered") or budget.get("hard_budget_triggered")))
        checkpoints = metadata.get("checkpoints") if isinstance(metadata.get("checkpoints"), list) else []
        if checkpoints and str(row.get("status") or "") in CHECKPOINT_SAFE_STATUSES:
            resumable_runs += 1
        if "elapsed_ms" in health:
            try:
                durations.append(float(health.get("elapsed_ms")) / 1000.0)
            except Exception:
                pass
        elif row.get("started_at") and row.get("finished_at"):
            try:
                started = datetime.fromisoformat(str(row.get("started_at")))
                finished = datetime.fromisoformat(str(row.get("finished_at")))
                durations.append(max(0.0, (finished - started).total_seconds()))
            except Exception:
                pass
    for call in tool_calls:
        retry_count += int(call.get("retry_count") or 0)
        error_type = str(call.get("error_type") or "")
        timeout_count += int(ERROR_TIMEOUT in error_type)
        metadata = call.get("metadata_json") if isinstance(call.get("metadata_json"), dict) else call.get("metadata")
        metadata = dict(metadata or {})
        reliability = metadata.get("runtime_reliability") if isinstance(metadata.get("runtime_reliability"), dict) else {}
        state = str(reliability.get("circuit_state") or "")
        if state:
            circuit_states[state] = circuit_states.get(state, 0) + 1

    latency = LatencyTracker()
    for value in durations:
        latency.record(value)
    latency_summary = latency.summary()
    return {
        "run_count": run_count,
        "success_rate": (completed / run_count) if run_count else None,
        "failed_rate": (failed / run_count) if run_count else None,
        "p50_latency": latency_summary.get("p50"),
        "p95_latency": latency_summary.get("p95"),
        "tool_call_count": len(tool_calls),
        "tool_failure_rate": (
            sum(1 for row in tool_calls if str(row.get("status") or "") not in {"success", "completed", "succeeded", "ok"}) / len(tool_calls)
            if tool_calls
            else None
        ),
        "retry_count": retry_count,
        "timeout_count": timeout_count,
        "circuit_states": circuit_states,
        "over_budget_count": over_budget_count,
        "resumable_run_count": resumable_runs,
    }

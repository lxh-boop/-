from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


NON_RETRYABLE_TEXT = (
    "404",
    "not found",
    "permission",
    "unauthorized",
    "forbidden",
    "schema",
    "duplicate column",
    "no such table",
    "parameter",
    "invalid argument",
)


@dataclass(frozen=True)
class RetryPolicy:
    timeout_seconds: int = 10
    max_retries: int = 2
    backoff_seconds: tuple[float, ...] = (2.0, 5.0)
    non_retryable_text: tuple[str, ...] = field(default_factory=lambda: NON_RETRYABLE_TEXT)


@dataclass(frozen=True)
class RetryResult:
    value: Any = None
    retry_count: int = 0
    warnings: list[str] = field(default_factory=list)


def is_non_retryable_error(exc: BaseException, policy: RetryPolicy | None = None) -> bool:
    policy = policy or RetryPolicy()
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in policy.non_retryable_text)


def run_with_retry(
    func: Callable[[], Any],
    policy: RetryPolicy | None = None,
    retryable: Callable[[BaseException], bool] | None = None,
) -> RetryResult:
    policy = policy or RetryPolicy()
    warnings: list[str] = []
    last_error: BaseException | None = None
    attempts = max(1, int(policy.max_retries) + 1)
    for attempt in range(attempts):
        try:
            return RetryResult(value=func(), retry_count=attempt, warnings=warnings)
        except Exception as exc:
            last_error = exc
            should_retry = retryable(exc) if retryable else not is_non_retryable_error(exc, policy)
            if not should_retry or attempt >= attempts - 1:
                raise
            delay = policy.backoff_seconds[min(attempt, len(policy.backoff_seconds) - 1)] if policy.backoff_seconds else 0.0
            warnings.append(f"retry {attempt + 1}/{attempts - 1} after {type(exc).__name__}: {exc}")
            if delay > 0:
                time.sleep(delay)
    if last_error:
        raise last_error
    return RetryResult()

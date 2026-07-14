from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.runtime_reliability import (
    CircuitBreaker,
    LatencyTracker,
    RetryPolicy,
    RuntimeTimeoutError,
    run_with_retry,
    run_with_timeout,
    summarize_large_output,
)
from database.sqlite_store import run_with_sqlite_lock_retry


def simulate_readonly_concurrency(task_count: int = 10) -> dict[str, Any]:
    tracker = LatencyTracker()

    def task(index: int) -> dict[str, Any]:
        started = time.perf_counter()
        result = run_with_retry(
            lambda: {"index": index, "success": True},
            policy=RetryPolicy(max_attempts=2),
            read_only=True,
        )
        tracker.record(time.perf_counter() - started)
        return result

    with ThreadPoolExecutor(max_workers=min(8, max(1, task_count))) as executor:
        results = list(executor.map(task, range(task_count)))
    return {
        "case": "readonly_concurrency",
        "success": all(item["success"] for item in results),
        "task_count": task_count,
        "latency": tracker.summary(),
    }


def simulate_timeout() -> dict[str, Any]:
    try:
        run_with_timeout(lambda: time.sleep(0.2), timeout_seconds=0.02)
    except RuntimeTimeoutError as exc:
        return {"case": "tool_timeout", "success": True, "error": str(exc)}
    return {"case": "tool_timeout", "success": False, "error": ""}


def simulate_db_lock_retry() -> dict[str, Any]:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = run_with_sqlite_lock_retry(flaky, max_attempts=4, base_delay_seconds=0.001)
    return {"case": "database_lock_retry", "success": result == "ok", "attempts": attempts["count"]}


def simulate_circuit_breaker() -> dict[str, Any]:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    return {"case": "circuit_breaker", "success": breaker.state == "open" and not breaker.allow_request(), "state": breaker.state}


def simulate_large_output() -> dict[str, Any]:
    summary = summarize_large_output("x" * 5000, max_chars=512)
    return {"case": "large_output", "success": bool(summary["truncated"]) and summary["original_length"] == 5000, "summary": summary}


def run_runtime_fault_injection_suite(task_count: int = 10) -> dict[str, Any]:
    cases = [
        simulate_readonly_concurrency(task_count=task_count),
        simulate_timeout(),
        simulate_db_lock_retry(),
        simulate_circuit_breaker(),
        simulate_large_output(),
    ]
    return {
        "case_count": len(cases),
        "success_count": sum(1 for item in cases if item.get("success")),
        "all_passed": all(item.get("success") for item in cases),
        "cases": cases,
    }

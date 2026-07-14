from __future__ import annotations

import sqlite3
import time

import pytest

from agent.runtime import AgentRuntimeRecorder, RUN_PLANNING
from agent.runtime_reliability import (
    CancellationToken,
    CircuitBreaker,
    CircuitBreakerRegistry,
    ERROR_VALIDATION,
    LatencyTracker,
    RetryPolicy,
    RuntimeBudget,
    RuntimeBudgetExceeded,
    RuntimeCheckpointer,
    RuntimePolicy,
    RuntimeTimeoutError,
    collect_runtime_health_summary,
    execute_with_policy,
    recover_run_from_checkpoint,
    run_with_retry,
    run_with_timeout,
    summarize_large_output,
)
from database.sqlite_store import run_with_sqlite_lock_retry
from evaluation.runtime_fault_injection import run_runtime_fault_injection_suite


def test_run_with_timeout_raises_for_slow_tool():
    with pytest.raises(RuntimeTimeoutError):
        run_with_timeout(lambda: time.sleep(0.2), timeout_seconds=0.02)


def test_readonly_retry_retries_but_write_does_not_retry():
    attempts = {"read": 0, "write": 0}

    def flaky_read():
        attempts["read"] += 1
        if attempts["read"] < 2:
            raise RuntimeError("temporary")
        return "ok"

    def flaky_write():
        attempts["write"] += 1
        raise RuntimeError("write failed")

    assert run_with_retry(flaky_read, policy=RetryPolicy(max_attempts=3), read_only=True) == "ok"
    with pytest.raises(RuntimeError):
        run_with_retry(flaky_write, policy=RetryPolicy(max_attempts=3), read_only=False)
    assert attempts["read"] == 2
    assert attempts["write"] == 1


def test_execute_with_policy_retries_only_retryable_readonly_failures():
    attempts = {"count": 0}
    policy = RuntimePolicy(max_retry_attempts=3, retry_backoff_seconds=0.001, tool_timeout_seconds=0.2)

    def flaky_read():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary network failure")
        return {"ok": True}

    result, metadata = execute_with_policy(
        flaky_read,
        tool_name="readonly_tool",
        read_only=True,
        policy=policy,
        budget=RuntimeBudget(policy),
        circuit_registry=CircuitBreakerRegistry(policy),
    )

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert metadata.retry_count == 1
    assert metadata.attempts[0]["error_type"] == "transient"


def test_default_policy_scopes_cold_start_budget_to_readonly_rag_tools():
    policy = RuntimePolicy.default()

    assert policy.resolve_for_tool("ranking").tool_timeout_seconds == 30.0
    assert policy.resolve_for_tool("stock_rag").tool_timeout_seconds == 90.0
    assert policy.resolve_for_tool("stock_rag").max_retry_attempts == 1
    assert policy.resolve_for_tool("evidence.search_rag").tool_timeout_seconds == 90.0


def test_non_retryable_validation_failure_fails_immediately():
    attempts = {"count": 0}
    policy = RuntimePolicy(max_retry_attempts=3, retry_backoff_seconds=0.001, tool_timeout_seconds=0.2)

    def invalid_tool():
        attempts["count"] += 1
        raise ValueError("invalid parameter")

    with pytest.raises(ValueError) as exc_info:
        execute_with_policy(
            invalid_tool,
            tool_name="validation_tool",
            read_only=True,
            policy=policy,
            budget=RuntimeBudget(policy),
            circuit_registry=CircuitBreakerRegistry(policy),
        )

    assert attempts["count"] == 1
    assert exc_info.value.runtime_metadata["error_type"] == ERROR_VALIDATION
    assert exc_info.value.runtime_metadata["retry_count"] == 0


def test_write_operation_is_not_retried_by_runtime_policy():
    attempts = {"count": 0}
    policy = RuntimePolicy(max_retry_attempts=3, retry_backoff_seconds=0.001, tool_timeout_seconds=0.2)

    def write_tool():
        attempts["count"] += 1
        raise RuntimeError("temporary write failure")

    with pytest.raises(RuntimeError) as exc_info:
        execute_with_policy(
            write_tool,
            tool_name="write_tool",
            read_only=False,
            policy=policy,
            budget=RuntimeBudget(policy),
            circuit_registry=CircuitBreakerRegistry(policy),
        )

    assert attempts["count"] == 1
    assert exc_info.value.runtime_metadata["retry_count"] == 0


def test_cancellation_token_blocks_runtime_work():
    token = CancellationToken()
    token.cancel("user_cancelled")

    with pytest.raises(RuntimeError, match="runtime_cancelled"):
        run_with_retry(lambda: "ok", cancellation=token)


def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
    assert breaker.allow_request()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == "open"
    assert not breaker.allow_request()


def test_circuit_breaker_half_open_and_close_after_recovery():
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=0.01)
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow_request()

    time.sleep(0.02)
    assert breaker.state == "half_open"
    assert breaker.allow_request()
    breaker.record_success()
    assert breaker.state == "closed"


def test_budget_soft_and_hard_limits_are_enforced():
    policy = RuntimePolicy(max_tool_calls=2, soft_token_budget=5, hard_token_budget=10, hard_llm_call_budget=99)
    budget = RuntimeBudget(policy)

    budget.record_tool_call(token_estimate=6)
    assert budget.should_reduce_optional_work() is True
    assert budget.hard_budget_triggered is False

    budget.record_tool_call(token_estimate=5)
    assert budget.hard_budget_triggered is True
    with pytest.raises(RuntimeBudgetExceeded):
        budget.ensure_can_start_tool()


def test_checkpoint_redacts_sensitive_values_and_recovers_readonly_run(tmp_path):
    db_path = tmp_path / "agent_quant.db"
    runtime = AgentRuntimeRecorder(user_id="u1", goal="readonly recovery", db_path=db_path)
    runtime.transition_run(RUN_PLANNING, "test")
    checkpoint = RuntimeCheckpointer(str(db_path)).save(
        run_id=runtime.run_id,
        stage=RUN_PLANNING,
        pending_tasks=[{"intent": "stock_rag", "confirmation_token": "secret-token"}],
        references={"api_key": "secret-key", "note": "safe"},
    )

    assert checkpoint["pending_tasks"][0]["confirmation_token"] == "***"
    assert checkpoint["references"]["api_key"] == "***"

    recovered = recover_run_from_checkpoint(run_id=runtime.run_id, db_path=str(db_path))
    assert recovered["success"] is True
    assert recovered["resume_entrypoint"] == "readonly_resume"
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_write_checkpoint_recovers_to_revalidate_not_commit(tmp_path):
    db_path = tmp_path / "agent_quant.db"
    runtime = AgentRuntimeRecorder(user_id="u1", goal="write recovery", db_path=db_path)
    runtime.transition_run(RUN_PLANNING, "test")
    RuntimeCheckpointer(str(db_path)).save(
        run_id=runtime.run_id,
        stage="waiting_for_approval",
        pending_tasks=[{"intent": "confirm_execute", "plan_id": "plan_1"}],
        write_intent=True,
    )

    recovered = recover_run_from_checkpoint(run_id=runtime.run_id, db_path=str(db_path))
    assert recovered["success"] is True
    assert recovered["resume_entrypoint"] == "revalidate"
    assert "commit is not resumed automatically" in recovered["message"]


def test_concurrent_recovery_lock_blocks_second_recovery(tmp_path):
    db_path = tmp_path / "agent_quant.db"
    runtime = AgentRuntimeRecorder(user_id="u1", goal="locked recovery", db_path=db_path)
    runtime.transition_run(RUN_PLANNING, "test")
    checkpointer = RuntimeCheckpointer(str(db_path))
    checkpointer.save(run_id=runtime.run_id, stage=RUN_PLANNING, pending_tasks=[{"intent": "ranking"}])
    assert checkpointer.acquire_recovery_lock(runtime.run_id, owner="test") is True
    try:
        recovered = recover_run_from_checkpoint(run_id=runtime.run_id, db_path=str(db_path))
        assert recovered["success"] is False
        assert recovered["error_type"] == "recovery_already_running"
    finally:
        checkpointer.release_recovery_lock(runtime.run_id)


def test_runtime_health_summary_counts_retries_circuit_budget_and_resumable_runs(tmp_path):
    db_path = tmp_path / "agent_quant.db"
    runtime = AgentRuntimeRecorder(user_id="u1", goal="health", db_path=db_path)
    runtime.transition_run(RUN_PLANNING, "test")
    runtime.merge_metadata(
        {
            "runtime_health": {"elapsed_ms": 1500},
            "budget_usage": {"soft_budget_triggered": True, "hard_budget_triggered": False},
        }
    )
    RuntimeCheckpointer(str(db_path)).save(
        run_id=runtime.run_id,
        stage=RUN_PLANNING,
        pending_tasks=[{"intent": "ranking"}],
    )
    runtime.record_tool_call(
        step_id=None,
        tool_name="ranking",
        arguments={},
        result={"success": False, "errors": ["timeout"], "message": "timeout"},
        reliability={"retry_count": 2, "circuit_state": "open"},
    )

    health = collect_runtime_health_summary(str(db_path))
    assert health["run_count"] == 1
    assert health["retry_count"] == 2
    assert health["timeout_count"] == 1
    assert health["circuit_states"]["open"] == 1
    assert health["over_budget_count"] == 1
    assert health["resumable_run_count"] == 1


def test_sqlite_lock_retry_retries_locked_operation():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert run_with_sqlite_lock_retry(flaky, max_attempts=4, base_delay_seconds=0.001) == "ok"
    assert attempts["count"] == 3


def test_latency_tracker_reports_p95_and_large_output_is_truncated():
    tracker = LatencyTracker()
    for value in [0.1, 0.2, 0.3, 0.4, 0.5]:
        tracker.record(value)
    summary = tracker.summary()
    large = summarize_large_output("x" * 5000, max_chars=100)

    assert summary["count"] == 5
    assert summary["p95"] >= 0.4
    assert large["truncated"] is True
    assert large["original_length"] == 5000
    assert len(large["preview"]) == 100


def test_runtime_fault_injection_suite_passes():
    report = run_runtime_fault_injection_suite(task_count=12)

    assert report["all_passed"] is True
    assert report["case_count"] == 5
    assert {case["case"] for case in report["cases"]} == {
        "readonly_concurrency",
        "tool_timeout",
        "database_lock_retry",
        "circuit_breaker",
        "large_output",
    }

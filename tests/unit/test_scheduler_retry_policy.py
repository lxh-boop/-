import pytest

from scheduler.retry_policy import RetryPolicy, is_non_retryable_error, run_with_retry


def test_retry_policy_retries_transient_failure(monkeypatch) -> None:
    monkeypatch.setattr("scheduler.retry_policy.time.sleep", lambda _: None)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("temporary timeout")
        return "ok"

    result = run_with_retry(flaky, RetryPolicy(max_retries=3, backoff_seconds=(0, 0, 0)))

    assert result.value == "ok"
    assert result.retry_count == 2
    assert len(result.warnings) == 2


def test_retry_policy_does_not_retry_non_retryable_error() -> None:
    assert is_non_retryable_error(RuntimeError("404 not found"))

    with pytest.raises(RuntimeError):
        run_with_retry(
            lambda: (_ for _ in ()).throw(RuntimeError("schema mismatch")),
            RetryPolicy(max_retries=5, backoff_seconds=(0,)),
        )

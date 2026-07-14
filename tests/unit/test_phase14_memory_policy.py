from __future__ import annotations

import json

from agent.memory import (
    MemoryPolicy,
    MemoryRecord,
    MemorySanitizer,
    MemoryType,
    MemoryVisibility,
)


def test_phase14_memory_policy_classifies_sensitive_and_raw_fields() -> None:
    policy = MemoryPolicy.default()

    assert policy.classify_field("confirmation_token") == MemoryVisibility.SECRET
    assert policy.classify_field("api_key") == MemoryVisibility.SECRET
    assert policy.classify_field("db_path") == MemoryVisibility.SYSTEM_ONLY
    assert policy.classify_field("stack_trace") == MemoryVisibility.AUDIT_ONLY
    assert policy.classify_field("raw_positions") == MemoryVisibility.TOOL_ONLY
    assert policy.classify_field("token_present") == MemoryVisibility.LLM_VISIBLE
    assert not policy.can_store_field("raw_evidence")


def test_phase14_memory_sanitizer_removes_secrets_paths_traces_and_summarizes_large_objects() -> None:
    sanitizer = MemorySanitizer()
    raw = {
        "summary": "ok",
        "confirmation_token": "abc",
        "api_key": "secret",
        "db_path": "D:\\stock_daily_app\\data\\agent_quant.db",
        "traceback": "Traceback (most recent call last): File \"x.py\", line 1",
        "raw_positions": [{"stock_code": "600519", "quantity": 100}],
        "nested": {"tushare_token": "ts_secret", "message": "api_key=abc D:\\stock_daily_app\\data\\agent_quant.db"},
    }

    safe = sanitizer.sanitize_for_storage(raw)
    encoded = json.dumps(safe, ensure_ascii=False)

    assert "confirmation_token" not in encoded
    assert "api_key" not in encoded
    assert "tushare_token" not in encoded
    assert "agent_quant.db" not in encoded
    assert "D:\\stock_daily_app" not in encoded
    assert "Traceback" not in encoded
    assert "raw_positions" not in encoded
    assert safe["positions_summary"]["count"] == 1
    assert safe["nested"]["message"] == "[redacted-secret] [redacted-path]"


def test_phase14_memory_policy_rejects_unconfirmed_or_one_time_user_fact() -> None:
    policy = MemoryPolicy.default()
    unconfirmed = MemoryRecord(
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="risk_preference",
        source_type="user_message",
        source_id="msg_1",
        content="Prefer high risk.",
    )
    one_time = MemoryRecord(
        memory_type=MemoryType.SEMANTIC,
        memory_subtype="preference",
        source_type="confirmed_user_preference",
        source_id="msg_2",
        content="Only this time reduce 600519.",
        metadata={"user_confirmed": True, "operation_scope": "one_time"},
    )

    assert "long_term_user_fact_requires_confirmation" in policy.validate_record(unconfirmed)
    assert "one_time_operation_cannot_be_long_term_memory" in policy.validate_record(one_time)


def test_phase14_memory_policy_allows_safe_approval_summary_only() -> None:
    policy = MemoryPolicy.default()
    safe = MemoryRecord(
        memory_type=MemoryType.WORKING,
        source_type="action_approval",
        source_id="approval_1",
        content="User approved plan.",
        metadata={
            "category": "approval",
            "plan_id": "plan_1",
            "status": "approved",
            "token_present": True,
            "summary": "approved one paper-trade plan",
        },
    )
    unsafe = MemoryRecord(
        memory_type=MemoryType.WORKING,
        source_type="action_approval",
        source_id="approval_2",
        content="User approved plan.",
        metadata={
            "category": "approval",
            "plan_id": "plan_2",
            "status": "approved",
            "confirmation_token": "abc",
        },
    )

    assert policy.allow_store(safe)[0] is True
    assert policy.allow_store(unsafe)[0] is False

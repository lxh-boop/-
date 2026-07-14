from __future__ import annotations

import json

from agent.communication import (
    AgentMessage,
    MessagePolicy,
    MessageSanitizer,
    MessageType,
    MessageVisibility,
)


def test_message_policy_classifies_sensitive_and_visible_fields() -> None:
    policy = MessagePolicy.default()

    assert policy.classify_field("confirmation_token") == MessageVisibility.SECRET
    assert policy.classify_field("api_key") == MessageVisibility.SECRET
    assert policy.classify_field("db_path") == MessageVisibility.SYSTEM_ONLY
    assert policy.classify_field("stack_trace") == MessageVisibility.AUDIT_ONLY
    assert policy.classify_field("raw_positions") == MessageVisibility.TOOL_ONLY
    assert policy.classify_field("summary") == MessageVisibility.LLM_VISIBLE
    assert policy.classify_field("artifact_refs") == MessageVisibility.LLM_VISIBLE
    assert policy.can_show_to_llm("summary")
    assert not policy.can_show_to_llm("confirmation_token")
    assert not policy.can_show_to_ui("db_path")


def test_sanitizer_removes_tokens_paths_and_stacks_from_llm_and_ui() -> None:
    message = AgentMessage(
        sender="write_gateway",
        receiver="ui",
        message_type=MessageType.APPROVAL_REQUESTED,
        payload={
            "plan_id": "plan1",
            "plan_hash": "hash1",
            "token_present": True,
            "confirmation_token": "raw-token",
            "confirmation_token_hash": "raw-hash",
            "api_key": "sk-secret",
            "db_path": "D:/stock_daily_app/data/agent_quant.db",
            "stack_trace": 'Traceback (most recent call last): File "internal.py", line 1',
            "summary": "需要确认模拟盘写操作",
        },
        metadata={"local_path": "D:/stock_daily_app/outputs/result.json"},
    )

    sanitizer = MessageSanitizer()
    llm_payload = sanitizer.sanitize_for_llm(message)
    ui_payload = sanitizer.sanitize_for_ui(message)
    audit_payload = sanitizer.sanitize_for_audit(message)
    llm_text = json.dumps(llm_payload, ensure_ascii=False, sort_keys=True)
    ui_text = json.dumps(ui_payload, ensure_ascii=False, sort_keys=True)
    audit_text = json.dumps(audit_payload, ensure_ascii=False, sort_keys=True)

    for secret in ["raw-token", "raw-hash", "sk-secret", "agent_quant.db", "internal.py", "result.json"]:
        assert secret not in llm_text
        assert secret not in ui_text
    assert "raw-token" not in audit_text
    assert "***" in audit_text
    assert llm_payload["payload"]["token_present"] is True
    assert llm_payload["payload"]["plan_id"] == "plan1"


def test_tool_visibility_keeps_tool_only_payload_but_not_secret_or_system_path_for_read_scope() -> None:
    payload = {
        "raw_evidence": [{"chunk_id": "chunk1", "body": "full evidence"}],
        "confirmation_token": "raw-token",
        "db_path": "D:/secret.db",
        "summary": "safe summary",
    }

    sanitizer = MessageSanitizer()
    read_payload = sanitizer.sanitize_for_tool(payload, permission_scope="read")
    system_payload = sanitizer.sanitize_for_tool(payload, permission_scope="system")
    read_text = json.dumps(read_payload, ensure_ascii=False, sort_keys=True)
    system_text = json.dumps(system_payload, ensure_ascii=False, sort_keys=True)

    assert "full evidence" in read_text
    assert "raw-token" not in read_text
    assert "secret.db" not in read_text
    assert "secret.db" in system_text

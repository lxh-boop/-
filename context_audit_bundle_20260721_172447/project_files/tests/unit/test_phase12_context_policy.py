from __future__ import annotations

import json

from agent.context import (
    ApprovalContext,
    ContextBundle,
    ContextPolicy,
    ContextSanitizer,
    ContextVisibility,
    RuntimeContext,
)


def test_policy_marks_secret_system_audit_and_summary_fields():
    policy = ContextPolicy.default()

    assert policy.visibility_for("confirmation_token") == ContextVisibility.SECRET
    assert policy.visibility_for("llm_api_key") == ContextVisibility.SECRET
    assert policy.visibility_for("db_path") == ContextVisibility.SYSTEM_ONLY
    assert policy.visibility_for("stack_trace") == ContextVisibility.AUDIT_ONLY
    assert policy.visibility_for("raw_evidence") == ContextVisibility.TOOL_ONLY
    assert policy.visibility_for("evidence_summary") == ContextVisibility.LLM_VISIBLE
    assert policy.visibility_for("artifact_refs") == ContextVisibility.LLM_VISIBLE


def test_sanitize_for_llm_removes_tokens_paths_and_internal_stacks():
    bundle = ContextBundle(
        user_id="u1",
        approval_context=ApprovalContext(
            pending_plan_id="plan_1",
            plan_hash="hash_1",
            token_present=True,
            pending_plan_summary={
                "operation_type": "rebalance",
                "confirmation_token": "secret-token",
                "confirmation_token_hash": "secret-hash",
            },
        ),
        runtime_context=RuntimeContext(
            run_id="run1",
            stack_trace='Traceback (most recent call last): File "secret.py", line 1',
            metadata={"db_path": "D:/secret/agent_quant.db", "api_key": "sk-secret"},
        ),
        metadata={"tushare_token": "ts-secret", "safe": "ok"},
    )

    payload = ContextSanitizer().sanitize_for_llm(bundle)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "secret-token" not in encoded
    assert "secret-hash" not in encoded
    assert "sk-secret" not in encoded
    assert "ts-secret" not in encoded
    assert "agent_quant.db" not in encoded
    assert "secret.py" not in encoded
    assert payload["approval_context"]["token_present"] is True
    assert payload["approval_context"]["pending_plan_id"] == "plan_1"


def test_sanitize_for_ui_hides_internal_stack_and_audit_redacts_secret():
    bundle = ContextBundle(
        runtime_context=RuntimeContext(stack_trace='Traceback (most recent call last): File "internal.py", line 2'),
        metadata={"confirmation_token": "raw-token", "safe": "ok"},
    )

    sanitizer = ContextSanitizer()
    ui_payload = sanitizer.sanitize_for_ui(bundle)
    audit_payload = sanitizer.sanitize_for_audit(bundle)
    ui_text = json.dumps(ui_payload, ensure_ascii=False, sort_keys=True)
    audit_text = json.dumps(audit_payload, ensure_ascii=False, sort_keys=True)

    assert "internal.py" not in ui_text
    assert "raw-token" not in ui_text
    assert "raw-token" not in audit_text
    assert "***" in audit_text
    assert audit_payload["metadata"]["safe"] == "ok"


def test_sanitize_for_tool_keeps_tool_only_payload_but_not_secret():
    value = {
        "raw_evidence": [{"chunk_id": "chunk_1", "body": "full evidence"}],
        "confirmation_token": "raw-token",
        "db_path": "D:/secret.db",
        "evidence_summary": [{"title": "summary"}],
    }

    read_payload = ContextSanitizer().sanitize_for_tool(value, permission_scope="read")
    system_payload = ContextSanitizer().sanitize_for_tool(value, permission_scope="system")
    read_text = json.dumps(read_payload, ensure_ascii=False, sort_keys=True)
    system_text = json.dumps(system_payload, ensure_ascii=False, sort_keys=True)

    assert "full evidence" in read_text
    assert "raw-token" not in read_text
    assert "secret.db" not in read_text
    assert "secret.db" in system_text

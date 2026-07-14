from agent.react import (
    ObservationEvent,
    ObservationType,
    ObservationVisibility,
    ObservePolicy,
    ObserveSanitizer,
)


def test_phase15_observe_policy_field_visibility_and_redaction_rules():
    policy = ObservePolicy.default()

    assert policy.classify_field("confirmation_token") is ObservationVisibility.SECRET
    assert policy.classify_field("api_key") is ObservationVisibility.SECRET
    assert policy.classify_field("tushare_token") is ObservationVisibility.SECRET
    assert policy.classify_field("db_path") is ObservationVisibility.SYSTEM_ONLY
    assert policy.classify_field("stack_trace") is ObservationVisibility.AUDIT_ONLY
    assert policy.classify_field("raw_positions") is ObservationVisibility.TOOL_ONLY
    assert policy.classify_field("raw_evidence") is ObservationVisibility.TOOL_ONLY
    assert policy.classify_field("raw_tool_payload") is ObservationVisibility.TOOL_ONLY
    assert policy.classify_field("summary") is ObservationVisibility.LLM_VISIBLE
    assert policy.classify_field("token_present") is ObservationVisibility.LLM_VISIBLE


def test_phase15_observe_policy_replan_rules():
    policy = ObservePolicy.default()

    assert policy.requires_replan_check(ObservationType.TOOL_EMPTY_RESULT)
    assert policy.requires_replan_check(ObservationType.TOOL_ERROR)
    assert policy.requires_replan_check(ObservationType.CONTEXT_INSUFFICIENT)
    assert policy.requires_replan_check(ObservationType.EVIDENCE_INSUFFICIENT)
    assert policy.requires_replan_check(ObservationType.TOOL_PERMISSION_BLOCKED)
    assert policy.requires_replan_check(ObservationType.APPROVAL_REQUIRED)
    assert not policy.requires_replan_check(ObservationType.TOOL_SUCCESS)
    assert not policy.requires_replan_check(ObservationType.REPORT_READY)


def test_phase15_observe_sanitizer_removes_secrets_paths_and_stack_for_llm_ui():
    event = ObservationEvent(
        observation_type=ObservationType.TOOL_ERROR,
        summary="failed with confirmation_token=abc123",
        detail={
            "confirmation_token": "abc123",
            "api_key": "sk-test",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
            "stack_trace": 'Traceback (most recent call last): File "x.py", line 1',
            "raw_tool_payload": {"artifact_id": "art_1", "secret": "hidden"},
        },
        error={
            "error_type": "runtime_error",
            "traceback": 'Traceback (most recent call last): File "x.py", line 1',
        },
    )

    sanitizer = ObserveSanitizer()
    llm = sanitizer.sanitize_for_llm(event)
    ui = sanitizer.sanitize_for_ui(event)
    text = f"{llm} {ui}"

    assert "abc123" not in text
    assert "sk-test" not in text
    assert "agent_quant.db" not in text
    assert "Traceback" not in text
    assert "raw_tool_payload" not in text
    assert "tool_payload_summary" in str(llm)


def test_phase15_observe_sanitizer_context_projection_is_summary_and_refs_only():
    event = ObservationEvent(
        observation_type=ObservationType.TOOL_EMPTY_RESULT,
        summary="no chunks",
        detail={"raw_evidence": [{"chunk_id": "chunk_1", "text": "full"}]},
        artifact_refs=[{"artifact_id": "art_1", "path": r"D:\secret\artifact.json"}],
    )
    context = ObserveSanitizer().sanitize_for_context(event)

    assert context["summary"] == "no chunks"
    assert context["artifact_refs"][0]["artifact_id"] == "art_1"
    assert "detail" not in context
    assert "raw_evidence" not in str(context)
    assert "D:\\secret" not in str(context)


def test_phase15_observe_sanitizer_audit_redacts_secret_but_keeps_error_type():
    event = ObservationEvent(
        observation_type=ObservationType.TOOL_ERROR,
        detail={"confirmation_token": "abc123"},
        error={"error_type": "runtime_error", "confirmation_token": "abc123"},
    )
    audit = ObserveSanitizer().sanitize_for_audit(event)

    assert audit["detail"]["confirmation_token"] == "***"
    assert audit["error"]["error_type"] == "runtime_error"
    assert audit["error"]["confirmation_token"] == "***"

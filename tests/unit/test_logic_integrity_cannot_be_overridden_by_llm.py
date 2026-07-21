from agent.logic_integrity import feature_unavailable_payload, validate_agent_logic_integrity


def test_logic_integrity_cannot_be_overridden_by_llm() -> None:
    integrity = validate_agent_logic_integrity(write_requested=True, write_allowed=False)
    payload = feature_unavailable_payload(integrity, language="zh")

    assert payload["status"] == "feature_unavailable"
    assert payload["safe_to_write"] is False
    assert payload["retryable"] is False


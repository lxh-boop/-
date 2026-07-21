from agent.logic_integrity import feature_unavailable_payload, validate_agent_logic_integrity


def test_feature_unavailable_not_overridden_by_llm() -> None:
    payload = feature_unavailable_payload(validate_agent_logic_integrity(portfolio_state={"safe_to_continue": False}), language="en")

    assert payload["retryable"] is False
    assert payload["requires_version_update"] is True


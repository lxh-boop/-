from agent.logic_integrity import feature_unavailable_payload, validate_agent_logic_integrity


def test_feature_unavailable_blocks_write() -> None:
    payload = feature_unavailable_payload(validate_agent_logic_integrity(write_requested=True, write_allowed=False))

    assert payload["safe_to_write"] is False
    assert payload["no_write_performed"] is True


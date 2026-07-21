from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_blocks_write() -> None:
    result = validate_agent_logic_integrity(write_requested=True, write_allowed=False)

    assert result.status == "logic_error"
    assert result.safe_to_write is False
    assert result.recommended_action == "feature_unavailable"


from agent.logic_integrity import validate_agent_logic_integrity


def test_feature_unavailable_works_without_llm() -> None:
    result = validate_agent_logic_integrity(portfolio_state={"consistency_status": "rejected"})

    assert result.recommended_action == "feature_unavailable"


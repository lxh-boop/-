from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_detects_missing_replan_execution() -> None:
    result = validate_agent_logic_integrity(
        completion={"next_action": "replan_readonly"},
        replan_audit=[{"status": "blocked"}],
        replan_count=0,
    )

    assert result.status == "logic_error"
    assert "replan_required_but_not_executed" in result.errors


from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_detects_completion_false_success() -> None:
    result = validate_agent_logic_integrity(
        completion={"status": "completed"},
        task_results={"a": {"success": False, "data": {}}},
    )

    assert result.status == "logic_error"
    assert "completion_false_success" in result.errors


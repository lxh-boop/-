from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_detects_count_mismatch() -> None:
    result = validate_agent_logic_integrity(
        task_plan={"tasks": [{"task_id": "a"}, {"task_id": "b"}]},
        task_results={"a": {"success": True, "data": {"report": {"ok": True}}}},
    )

    assert result.status == "logic_error"
    assert "task_plan_result_count_mismatch" in result.errors


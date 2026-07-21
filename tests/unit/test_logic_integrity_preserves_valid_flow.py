from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_preserves_valid_flow() -> None:
    result = validate_agent_logic_integrity(
        portfolio_state={"consistency_status": "consistent", "snapshot_id": "s1"},
        risk_report={"snapshot_id": "s1"},
        task_plan={"tasks": [{"task_id": "a"}], "expected_outputs": ["report"]},
        task_results={"a": {"success": True, "data": {"report": {"ok": True}}}},
        completion={"status": "completed"},
    )

    assert result.status == "ok"
    assert result.safe_to_write is True


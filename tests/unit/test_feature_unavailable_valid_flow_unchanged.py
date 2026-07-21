from agent.logic_integrity import validate_agent_logic_integrity


def test_feature_unavailable_valid_flow_unchanged() -> None:
    integrity = validate_agent_logic_integrity(task_results={"a": {"success": True, "data": {"report": "ok"}}})

    assert integrity.status == "ok"
    assert integrity.safe_to_continue is True


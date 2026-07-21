from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_detects_empty_required_artifact() -> None:
    result = validate_agent_logic_integrity(
        task_results={"a": {"success": True, "data": {"report": ""}}},
        required_artifacts=["report"],
    )

    assert result.status == "logic_error"
    assert result.error_code == "required_artifact_empty"


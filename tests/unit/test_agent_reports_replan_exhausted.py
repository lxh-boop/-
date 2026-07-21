from agent.logic_integrity import validate_agent_logic_integrity


def test_agent_reports_replan_exhausted() -> None:
    integrity = validate_agent_logic_integrity(replan_audit=[{"status": "bounded_replan_exhausted"}])

    assert integrity.status == "logic_error"
    assert integrity.error_code == "replan_no_reliable_progress"


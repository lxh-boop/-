from agent.logic_integrity import feature_unavailable_payload, validate_agent_logic_integrity
from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, no_evidence, readonly_results


def test_scenario_a_valid_flow_remains_available() -> None:
    assert validate_agent_logic_integrity(task_results={"a": {"success": True, "data": {"report": "ok"}}}).status == "ok"


def test_scenario_b_asset_mismatch_is_feature_unavailable_without_write() -> None:
    payload = feature_unavailable_payload(validate_agent_logic_integrity(portfolio_state={"consistency_status": "rejected"}))
    assert payload["status"] == "feature_unavailable"
    assert payload["no_write_performed"] is True


def test_scenario_c_snapshot_id_conflict_is_blocked() -> None:
    integrity = validate_agent_logic_integrity(portfolio_state={"snapshot_id": "state"}, risk_report={"snapshot_id": "risk"})
    assert integrity.error_code == "portfolio_snapshot_id_mismatch"


def test_scenario_d_replan_with_new_evidence_can_continue() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_with_output({"market_evidence": "fresh"}))
    assert outcome["status"] == "executed"


def test_scenario_e_replan_without_progress_becomes_unavailable() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=no_evidence)
    integrity = validate_agent_logic_integrity(replan_audit=outcome["replan_audit"], replan_count=outcome["replan_count"])
    assert integrity.status == "logic_error"


def test_scenario_f_replan_exhausted_becomes_unavailable() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=2, replan_limit=2, replan_audit=[], task_results=readonly_results())
    integrity = validate_agent_logic_integrity(replan_audit=outcome["replan_audit"], replan_count=2, replan_limit=2)
    assert integrity.status == "logic_error"


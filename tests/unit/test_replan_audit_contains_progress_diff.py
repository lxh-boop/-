from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, readonly_results


def test_replan_audit_contains_progress_diff() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_with_output({"market_evidence": "new"}))

    audit = outcome["replan_audit"][-1]
    for field in ("round", "trigger_source", "plan_signature", "result_signature", "produced_outputs_before", "produced_outputs_after", "new_or_changed_outputs", "missing_outputs_before", "missing_outputs_after", "progress_status", "stop_reason"):
        assert field in audit


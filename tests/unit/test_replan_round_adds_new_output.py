from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, readonly_results


def test_replan_round_adds_new_output() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_with_output({"market_evidence": "new"}))

    assert outcome["status"] == "executed"
    assert outcome["replan_audit"][-1]["new_or_changed_outputs"]["market_evidence"] == "new"


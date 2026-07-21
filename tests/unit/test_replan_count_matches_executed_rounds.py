from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, readonly_results


def test_replan_count_matches_executed_rounds() -> None:
    first = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_with_output({"market_evidence": "new"}))
    second = consume_readonly_replan(source="critic", action="replan", replan_count=first["replan_count"], replan_limit=2, replan_audit=first["replan_audit"], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_with_output({"market_evidence": "new"}))

    executed = [item for item in second["replan_audit"] if item.get("executed_tasks")]
    assert second["replan_count"] == len(executed)


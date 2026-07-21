from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_completion_replan_is_consumed() -> None:
    result = consume_readonly_replan(source="completion", action="replan_readonly", replan_count=0, replan_limit=1, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_success)

    assert result["replan_count"] == 1
    assert result["replan_audit"][0]["source"] == "completion"

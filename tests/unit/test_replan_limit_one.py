from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_limit_one() -> None:
    result = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=1, replan_audit=[], task_results=readonly_results(), execute_plan=execute_success)

    assert result["status"] == "executed"
    assert result["replan_count"] == 1

from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_stops_when_goal_completed() -> None:
    result = consume_readonly_replan(source="completion", action="finish", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), execute_plan=execute_success)

    assert result["consumed"] is False
    assert result["replan_count"] == 0

from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import readonly_results


def test_replan_goal_completed_stops() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), goal_completed=True)

    assert outcome["status"] == "goal_completed"
    assert outcome["replan_count"] == 0


from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, readonly_results


def test_replan_progress_can_continue_until_limit() -> None:
    first = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], user_goal={"goal_id": "one"}, execute_plan=execute_with_output({"market_evidence": "one"}))
    second = consume_readonly_replan(source="completion", action="replan", replan_count=first["replan_count"], replan_limit=2, replan_audit=first["replan_audit"], task_results=readonly_results(), missing_outputs=["market_evidence"], user_goal={"goal_id": "two"}, execute_plan=execute_with_output({"market_evidence": "two"}))

    assert first["status"] == "executed"
    assert second["status"] == "executed"
    assert second["replan_count"] == 2

from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import execute_with_output, readonly_results


def test_replan_same_result_stops_early() -> None:
    execute = execute_with_output({"market_evidence": "same"})
    first = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=3, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], user_goal={"goal_id": "one"}, execute_plan=execute)
    results = {**readonly_results(), **first["execution"]["task_results"]}
    second = consume_readonly_replan(source="critic", action="replan", replan_count=first["replan_count"], replan_limit=3, replan_audit=first["replan_audit"], task_results=results, missing_outputs=["market_evidence"], user_goal={"goal_id": "two"}, execute_plan=execute)

    assert second["status"] == "no_progress"
    assert second["replan_audit"][-1]["stop_reason"] == "same_result_without_progress"

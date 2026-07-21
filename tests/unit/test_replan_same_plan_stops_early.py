from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import no_evidence, readonly_results


def test_replan_same_plan_stops_early() -> None:
    first = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=3, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=no_evidence)
    second = consume_readonly_replan(source="critic", action="replan", replan_count=first["replan_count"], replan_limit=3, replan_audit=first["replan_audit"], task_results=readonly_results(), missing_outputs=["market_evidence"], user_goal={"round": 2}, execute_plan=no_evidence)

    assert first["status"] == "no_progress"
    assert second["status"] == "no_progress"
    assert second["replan_count"] == 1


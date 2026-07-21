from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import no_evidence, readonly_results


def test_replan_no_progress_stops_before_limit() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=5, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=no_evidence)

    assert outcome["status"] == "no_progress"
    assert outcome["replan_count"] == 1


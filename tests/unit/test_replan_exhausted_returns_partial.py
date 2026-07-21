from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_exhausted_returns_partial() -> None:
    result = consume_readonly_replan(source="completion", action="replan", replan_count=2, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["target_portfolio"], execute_plan=execute_success)

    assert result["status"] == "bounded_replan_exhausted"
    assert result["execution"] == {}
    assert result["replan_audit"][-1]["missing_outputs"] == ["target_portfolio"]

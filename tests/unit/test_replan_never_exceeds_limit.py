from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_never_exceeds_limit() -> None:
    first = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=1, replan_audit=[], task_results=readonly_results(), execute_plan=execute_success)
    second = consume_readonly_replan(source="completion", action="replan", replan_count=first["replan_count"], replan_limit=1, replan_audit=first["replan_audit"], task_results=readonly_results(), execute_plan=execute_success)

    assert second["status"] == "bounded_replan_exhausted"
    assert second["replan_count"] == 1

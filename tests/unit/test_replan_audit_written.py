from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_audit_written() -> None:
    result = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), execute_plan=execute_success)

    assert result["replan_audit"][-1]["status"] == "executed"
    assert result["replan_audit"][-1]["planned_tasks"]

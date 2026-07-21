from agent.replan_execution import consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_replan_no_infinite_loop() -> None:
    count, audit = 0, []
    for _ in range(10):
        result = consume_readonly_replan(source="completion", action="replan", replan_count=count, replan_limit=2, replan_audit=audit, task_results=readonly_results(), execute_plan=execute_success)
        count, audit = result["replan_count"], result["replan_audit"]

    assert count == 1
    assert audit[-1]["status"] == "no_progress"

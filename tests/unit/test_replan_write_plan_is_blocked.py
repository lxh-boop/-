from agent.replan_execution import consume_readonly_replan
from replan_progress_test_helpers import readonly_results


def test_replan_write_plan_is_blocked() -> None:
    outcome = consume_readonly_replan(source="completion", action="replan", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), safe_to_continue=False)

    assert outcome["status"] == "logic_error"
    assert outcome["execution"] == {}


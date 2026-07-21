from agent.replan_execution import CANONICAL_REPLAN_READONLY, canonical_replan_action, consume_readonly_replan
from replan_test_helpers import execute_success, readonly_results


def test_critic_replan_is_consumed() -> None:
    result = consume_readonly_replan(source="critic", action="REPLAN_READONLY", replan_count=0, replan_limit=2, replan_audit=[], task_results=readonly_results(), missing_outputs=["market_evidence"], execute_plan=execute_success)

    assert canonical_replan_action("REPLAN_READONLY") == CANONICAL_REPLAN_READONLY
    assert result["status"] == "executed"

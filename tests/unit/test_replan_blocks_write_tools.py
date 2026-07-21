from agent.replan_execution import validate_readonly_replan_tasks


def test_replan_blocks_write_tools() -> None:
    blocked = validate_readonly_replan_tasks([{"task_id": "replan_write", "intent": "one_time_position_operation", "parameters": {"stock_code": "000001"}}])

    assert blocked == [{"task_id": "replan_write", "intent": "one_time_position_operation", "reason": "write_task_not_allowed_in_replan"}]

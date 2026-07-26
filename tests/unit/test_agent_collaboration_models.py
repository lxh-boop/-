from agent.collaboration.models import (
    GraphAgentTask,
    GraphWorkerResult,
    ResultStatus,
)


def test_coordinator_views_do_not_expose_internal_task_or_tool_details():
    task = GraphAgentTask(
        task_id="task_1",
        run_id="run_1",
        session_id="session_1",
        assigned_agent="EVIDENCE_RESEARCHER",
        objective="分析两只股票",
        task_type="compare_stock_evidence",
        user_id="user_1",
        metadata={
            "private_internal_plan": [{"capability": "internal_capability", "arguments": {"stock_code": "600519"}}],
            "private_registry": ["internal_capability"],
        },
    )
    safe_task = task.safe_for_coordinator()
    assert "metadata" not in safe_task
    assert "private_internal_plan" not in str(safe_task)
    assert "stock_analysis" not in str(safe_task)

    result = GraphWorkerResult(
        task_id="task_1",
        agent_id="EVIDENCE_RESEARCHER",
        status=ResultStatus.COMPLETED,
        summary="分析完成",
        metadata={
            "task_type": "compare_stock_evidence",
            "internal_call_count": 2,
            "tool_calls": [{"tool_name": "stock_analysis"}],
            "raw_tool_payload": {"secret": "x"},
        },
    )
    safe_result = result.safe_for_coordinator()
    assert "internal_call_count" not in safe_result["metadata"]
    assert "tool_calls" not in safe_result["metadata"]
    assert "stock_analysis" not in str(safe_result)
    assert "raw_tool_payload" not in str(safe_result)

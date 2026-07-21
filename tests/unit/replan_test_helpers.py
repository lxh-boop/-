from __future__ import annotations

from typing import Any


def readonly_results() -> dict[str, dict[str, Any]]:
    return {
        "task_ranking": {
            "task_id": "task_ranking",
            "intent": "ranking",
            "success": True,
            "arguments": {"top_k": 10},
            "data": {"records": [{"stock_code": "000001"}]},
        }
    }


def execute_success(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": True,
        "execution_status": "completed",
        "task_results": {
            str(task["task_id"]): {
                "task_id": str(task["task_id"]),
                "intent": str(task["intent"]),
                "success": True,
                "data": {"market_evidence": True},
            }
            for task in tasks
        },
        "tool_calls": [],
        "warnings": [],
        "errors": [],
    }

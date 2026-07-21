from __future__ import annotations

from typing import Any

from replan_test_helpers import readonly_results


def execute_with_output(output: dict[str, Any]):
    def _execute(tasks: list[dict[str, Any]]) -> dict[str, Any]:
        task = tasks[-1]
        return {
            "success": True,
            "execution_status": "completed",
            "task_results": {
                task["task_id"]: {
                    "task_id": task["task_id"],
                    "intent": task["intent"],
                    "success": True,
                    "data": dict(output),
                }
            },
            "tool_calls": [{"tool_name": task["intent"], "success": True}],
        }

    return _execute


def no_evidence(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task = tasks[-1]
    return {
        "success": True,
        "execution_status": "completed",
        "task_results": {task["task_id"]: {"task_id": task["task_id"], "intent": task["intent"], "success": True, "data": {}}},
        "tool_calls": [],
    }


__all__ = ["execute_with_output", "no_evidence", "readonly_results"]


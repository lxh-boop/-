"""Deterministic execution ordering without business-data transport edges.

The runtime uses task dependencies only to decide *when* a Worker may execute.
Business data is shared through the run ContextBundle working memory and is not
carried along dependency edges.
"""
from __future__ import annotations

from typing import Any

from .models import CapabilityTask

_STAGE_ORDER = {
    "provider": 10,
    "analysis": 20,
    "decision": 30,
    "report": 40,
    "diagnostic": 40,
    "mutation": 50,
}


class TaskDependencyCompiler:
    def __init__(self, worker_directory: Any) -> None:
        self.worker_directory = worker_directory

    def compile(self, tasks: list[CapabilityTask]) -> dict[str, list[str]]:
        """Build conservative execution dependencies from Worker stages.

        Providers execute before analytical consumers selected for the same
        business request, analysis executes before decision Workers, and
        mutation Workers execute last.  No dependency is inferred from data
        names, so the DAG is never a hidden data-transport graph.
        """
        stages: dict[str, int] = {}
        for task in tasks:
            card = self.worker_directory.get(task.worker_id)
            stages[task.task_id] = _STAGE_ORDER.get(str(card.execution_stage or "analysis"), 20)

        result: dict[str, list[str]] = {task.task_id: [] for task in tasks}
        for task in tasks:
            current = stages[task.task_id]
            predecessors = [
                other.task_id
                for other in tasks
                if other.task_id != task.task_id and stages[other.task_id] < current
            ]
            # A diagnostic Worker is independent unless it is explicitly the
            # only later-stage task.  It reads runtime state directly.
            card = self.worker_directory.get(task.worker_id)
            if str(card.execution_stage) == "diagnostic":
                predecessors = []
            result[task.task_id] = list(dict.fromkeys(predecessors))
        return result


__all__ = ["TaskDependencyCompiler"]

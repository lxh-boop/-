"""Execute validated Main-Agent task DAGs against the Worker runtime."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Protocol

from .models import GraphAgentTask, GraphWorkerResult, ResultStatus


class WorkerRunner(Protocol):
    def run(
        self,
        task: GraphAgentTask,
        *,
        current_user_request: str,
        dependency_results: dict[str, dict[str, Any]],
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None = None,
    ) -> GraphWorkerResult: ...


def run_worker_dag(
    tasks: list[GraphAgentTask],
    *,
    specialist: WorkerRunner,
    query: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    language: str,
    execution_context: dict[str, Any],
    initial_results: dict[str, GraphWorkerResult] | None = None,
) -> tuple[
    dict[str, GraphWorkerResult],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Run ready tasks in parallel and block descendants of incomplete work."""

    results: dict[str, GraphWorkerResult] = dict(initial_results or {})
    pending = {
        task.task_id: task
        for task in tasks
        if task.task_id not in results
    }
    batches: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    batch_index = 0
    successful_dependency_statuses = {
        ResultStatus.COMPLETED,
        ResultStatus.PARTIAL,
        ResultStatus.PROPOSAL_READY,
    }
    while pending:
        ready = [
            task
            for task in pending.values()
            if all(
                dependency_id in results
                for dependency_id in task.dependency_task_ids
            )
        ]
        if not ready:
            for task in pending.values():
                results[task.task_id] = GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.NOT_EXECUTED,
                    focus_refs=task.focus_refs,
                    summary="任务依赖无法满足。",
                    warnings=["unresolved_task_dependency"],
                )
            break

        runnable: list[GraphAgentTask] = []
        for task in ready:
            blocked_dependencies = [
                dependency_id
                for dependency_id in task.dependency_task_ids
                if results[dependency_id].status
                not in successful_dependency_statuses
            ]
            if not blocked_dependencies:
                runnable.append(task)
                continue
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NOT_EXECUTED,
                focus_refs=task.focus_refs,
                summary="上游任务尚未完成，当前任务未执行。",
                warnings=[
                    "blocked_by_upstream_result:"
                    + ",".join(blocked_dependencies)
                ],
            )
            results[task.task_id] = result
            timeline.append(
                {
                    "task_id": task.task_id,
                    "agent_id": task.assigned_agent,
                    "capability_id": task.capability_id,
                    "status": result.status.value,
                    "summary": result.summary,
                }
            )
            pending.pop(task.task_id, None)
        if not runnable:
            continue

        batch_index += 1
        batches.append(
            {
                "batch_index": batch_index,
                "task_ids": [task.task_id for task in runnable],
                "agents": [task.assigned_agent for task in runnable],
                "capabilities": [
                    task.capability_id for task in runnable
                ],
                "parallel": len(runnable) > 1,
            }
        )
        with ThreadPoolExecutor(
            max_workers=min(4, len(runnable))
        ) as pool:
            futures = {
                pool.submit(
                    specialist.run,
                    task,
                    current_user_request=query,
                    dependency_results={
                        dependency_id: results[
                            dependency_id
                        ].safe_for_coordinator()
                        for dependency_id in task.dependency_task_ids
                        if dependency_id in results
                    },
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    language=language,
                    execution_context=execution_context,
                ): task
                for task in runnable
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = GraphWorkerResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                        status=ResultStatus.FAILED,
                        focus_refs=task.focus_refs,
                        summary="Worker 执行失败。",
                        warnings=[f"{type(exc).__name__}:{exc}"],
                    )
                results[task.task_id] = result
                timeline.append(
                    {
                        "task_id": task.task_id,
                        "agent_id": task.assigned_agent,
                        "capability_id": task.capability_id,
                        "status": result.status.value,
                        "summary": result.summary[:500],
                    }
                )
                pending.pop(task.task_id, None)
    return results, batches, timeline


__all__ = ["WorkerRunner", "run_worker_dag"]

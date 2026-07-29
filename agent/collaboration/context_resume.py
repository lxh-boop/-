"""Resume suspended Worker DAGs after Main-owned context clarification."""

from __future__ import annotations

from typing import Any, Callable

from agent.graph.contracts import refs_from

from .context_handoff import MainContextHandoff
from .models import (
    GraphAgentTask,
    GraphWorkerResult,
    ResultStatus,
    TaskStatus,
    WorkerContextRequest,
)
from .session_memory import SessionMemoryStore


def confirmed_memory_values(
    memory: SessionMemoryStore,
    session_id: str,
) -> dict[str, Any]:
    return {
        item.key: item.value
        for item in memory.list_latest(session_id, limit=100)
        if item.confirmed and not item.key.startswith("turn:")
    }


def context_requests(
    results: dict[str, GraphWorkerResult],
) -> list[WorkerContextRequest]:
    return [
        result.context_request
        for result in results.values()
        if result.context_request is not None
    ]


def descendant_task_ids(
    tasks: list[GraphAgentTask],
    root_ids: set[str],
) -> set[str]:
    descendants = set(root_ids)
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task.task_id in descendants:
                continue
            if set(task.dependency_task_ids).intersection(descendants):
                descendants.add(task.task_id)
                changed = True
    return descendants


def resume_context_snapshot(
    execution_context: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "as_of_time",
        "as_of_date",
        "resolved_context",
        "session_memory_values",
    }
    return {
        key: value
        for key, value in execution_context.items()
        if key in allowed
    }


class ContextResumeRuntime:
    """Own waiting-task restoration without expanding the Main coordinator."""

    def __init__(
        self,
        *,
        memory: SessionMemoryStore,
        handoff: MainContextHandoff,
        execute_plan: Callable[..., dict[str, Any]],
        empty_result: Callable[..., dict[str, Any]],
    ) -> None:
        self.memory = memory
        self.handoff = handoff
        self.execute_plan = execute_plan
        self.empty_result = empty_result

    def try_resume(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str,
        run_id: str,
        language: str,
        default_top_k: int,
        execution_context: dict[str, Any],
        memory_summary: str,
    ) -> dict[str, Any] | None:
        rows = self.memory.list_waiting_tasks(session_id)
        if not rows:
            return None
        task_payload = (
            rows[0].get("task")
            if isinstance(rows[0].get("task"), dict)
            else {}
        )
        anchor = GraphAgentTask.from_dict(task_payload)
        resume_state = (
            anchor.metadata.get("resume_state")
            if isinstance(anchor.metadata.get("resume_state"), dict)
            else {}
        )
        requests = [
            WorkerContextRequest.from_dict(item)
            for item in resume_state.get("context_requests") or []
            if isinstance(item, dict)
        ]
        if not requests:
            self.memory.cancel_waiting_tasks(
                session_id,
                status="superseded",
            )
            return None
        relation_state = (
            execution_context.get("conversation_state")
            if isinstance(
                execution_context.get("conversation_state"),
                dict,
            )
            else {}
        )
        turn_state = (
            execution_context.get("turn_resolution")
            if isinstance(
                execution_context.get("turn_resolution"),
                dict,
            )
            else {}
        )
        relation_type = str(
            relation_state.get("relation_type")
            or turn_state.get("relation_type")
            or execution_context.get("relation_type")
            or ""
        )
        decision = self.handoff.resolve_user_turn(
            query=query,
            requests=requests,
            memory_summary=memory_summary,
            language=language,
            relation_type=relation_type,
        )
        if decision.action == "cancel_waiting":
            self.memory.cancel_waiting_tasks(session_id)
            answer = (
                "The suspended request was cancelled."
                if language == "en"
                else "已取消等待补充信息的任务。"
            )
            return self.empty_result(
                answer=answer,
                success=True,
                status="cancelled",
            )
        if decision.action == "new_request":
            self.memory.cancel_waiting_tasks(
                session_id,
                status="superseded",
            )
            return None

        request_id = requests[0].request_id
        self.handoff.remember_clarification(
            session_id=session_id,
            request_id=request_id,
            values=decision.values,
        )
        memory_values, unresolved = self.handoff.memory_values(
            session_id,
            requests,
        )
        if unresolved:
            question = self.handoff.clarification_question(
                unresolved,
                language=language,
            )
            return {
                **self.empty_result(
                    answer=question,
                    success=False,
                    status="waiting_context",
                ),
                "need_clarification": True,
                "clarification_question": question,
                "clarification_request_id": request_id,
                "missing_context": [
                    item.to_dict() for item in unresolved
                ],
                "context_resume": {
                    "status": "partially_resolved",
                    "resolved_keys": sorted(memory_values),
                    "remaining_keys": [
                        item.key for item in unresolved
                    ],
                },
            }

        tasks = [
            GraphAgentTask.from_dict(item)
            for item in resume_state.get("tasks") or []
            if isinstance(item, dict)
        ]
        if not tasks or any(task.user_id != user_id for task in tasks):
            self.memory.cancel_waiting_tasks(session_id)
            return self.empty_result(
                answer=(
                    "The suspended task could not be restored safely."
                    if language == "en"
                    else "等待任务无法安全恢复，请重新发起请求。"
                ),
                success=False,
                status="failed",
                warnings=["invalid_waiting_task_resume_state"],
            )
        root_ids = {
            request.source_task_id for request in requests
        }
        rerun_ids = descendant_task_ids(tasks, root_ids)
        if max(
            (
                task.attempt
                for task in tasks
                if task.task_id in rerun_ids
            ),
            default=1,
        ) >= 3:
            self.memory.cancel_waiting_tasks(session_id)
            return self.empty_result(
                answer=(
                    "The task still lacks valid context after multiple attempts."
                    if language == "en"
                    else "多次补充后仍无法获得有效上下文，任务已停止。"
                ),
                success=False,
                status="failed",
                warnings=["context_resume_attempts_exhausted"],
            )
        previous_results = {
            str(task_id): GraphWorkerResult.from_dict(payload)
            for task_id, payload in dict(
                resume_state.get("results") or {}
            ).items()
            if isinstance(payload, dict)
            and str(task_id) not in rerun_ids
            and str(payload.get("status") or "")
            in {
                ResultStatus.COMPLETED.value,
                ResultStatus.PARTIAL.value,
                ResultStatus.PROPOSAL_READY.value,
            }
        }
        for task in tasks:
            if task.task_id in rerun_ids:
                task.run_id = run_id
                task.attempt += 1
                task.status = TaskStatus.CREATED
        for pending in rows:
            self.memory.mark_waiting_resumed(
                str(pending.get("waiting_id") or ""),
                new_run_id=run_id,
            )
        context = {
            **dict(resume_state.get("execution_context") or {}),
            **execution_context,
            "resolved_context": {
                **dict(
                    resume_state.get("resolved_context") or {}
                ),
                **memory_values,
            },
            "session_memory_values": confirmed_memory_values(
                self.memory,
                session_id,
            ),
            "context_resume_request_id": request_id,
        }
        result = self.execute_plan(
            tasks=tasks,
            query=str(resume_state.get("query") or ""),
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            default_top_k=int(
                resume_state.get("default_top_k") or default_top_k
            ),
            language=str(resume_state.get("language") or language),
            execution_context=context,
            focus_refs=refs_from(
                resume_state.get("focus_refs") or []
            ),
            resolution_audit=dict(
                resume_state.get("resolution_audit") or {}
            ),
            plan_meta=dict(resume_state.get("plan_meta") or {}),
            initial_results=previous_results,
        )
        result["context_resume"] = {
            "status": "resumed",
            "request_id": request_id,
            "resolved_keys": sorted(memory_values),
            "rerun_task_ids": sorted(rerun_ids),
        }
        return result


__all__ = [
    "ContextResumeRuntime",
    "confirmed_memory_values",
    "context_requests",
    "descendant_task_ids",
    "resume_context_snapshot",
]

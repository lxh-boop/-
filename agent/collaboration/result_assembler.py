"""Assemble public Main-Agent results from sanitized Worker contracts."""

from __future__ import annotations

from typing import Any

from agent.graph.contracts import GraphRef

from .agent_directory import AgentDirectory
from .models import GraphAgentTask, GraphWorkerResult, ResultStatus


def _fallback_answer(
    results: dict[str, GraphWorkerResult],
    language: str,
) -> str:
    summaries = [
        result.summary for result in results.values() if result.summary
    ]
    if summaries:
        return "\n\n".join(summaries)
    if language == "en":
        return (
            "The system cannot answer because the required data path "
            "returned no result."
        )
    return "目前不能回答，相关数据链路尚未返回结果。"


def assemble_main_result(
    *,
    tasks: list[GraphAgentTask],
    results: dict[str, GraphWorkerResult],
    batches: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    directory: AgentDirectory,
    language: str,
    question: str,
    request_id: str,
    graph_id: str,
    focus_refs: list[GraphRef],
    resolution_audit: dict[str, Any],
    plan_meta: dict[str, Any],
) -> dict[str, Any]:
    public_results = {
        task_id: result.safe_for_coordinator()
        for task_id, result in results.items()
    }
    finalizer_task_ids = {
        task.task_id
        for task in tasks
        if task.capability_id
        and directory.resolve(task.capability_id).can_finalize
    }
    report = next(
        (
            results[task.task_id]
            for task in tasks
            if task.task_id in finalizer_task_ids
            and task.task_id in results
            and results[task.task_id].summary
        ),
        None,
    )
    answer = (
        report.summary
        if report and report.summary
        else _fallback_answer(results, language)
    )
    statuses = [result.status for result in results.values()]
    need_context = [
        item
        for result in results.values()
        for item in result.missing_items
        if item.blocking
    ]
    failed = sum(
        status
        in {
            ResultStatus.FAILED,
            ResultStatus.BLOCKED,
            ResultStatus.NOT_EXECUTED,
        }
        for status in statuses
    )
    completed = sum(
        status
        in {
            ResultStatus.COMPLETED,
            ResultStatus.PARTIAL,
            ResultStatus.PROPOSAL_READY,
        }
        for status in statuses
    )
    execution_status = (
        "waiting_context"
        if need_context
        else "completed"
        if failed == 0
        else "partially_completed"
        if completed
        else "failed"
    )
    success = completed > 0 and failed == 0 and not need_context
    internal_count = sum(
        item.get("status") != "not_executed" for item in timeline
    )
    return {
        "success": success,
        "answer": question or answer,
        "task_results": public_results,
        "graph_worker_results": {
            "contract_version": "graph_worker_results.v1",
            "items": list(public_results.values()),
            "task_count": len(public_results),
            "completed_count": completed,
            "failed_count": failed,
            "waiting_context_count": len(need_context),
        },
        "tool_calls": [],
        "internal_tool_call_count": internal_count,
        "execution_order": [
            task.task_id for task in tasks if task.task_id in results
        ],
        "execution_batches": batches,
        "warnings": [
            warning
            for result in results.values()
            for warning in result.warnings
        ],
        "errors": [],
        "execution_status": execution_status,
        "need_clarification": bool(need_context),
        "clarification_question": question,
        "clarification_request_id": request_id,
        "missing_context": [
            item.to_dict() for item in need_context
        ],
        "observations": timeline,
        "replan_audit": [],
        "replan_count": 0,
        "invalid_replan_block_count": 0,
        "replan_limits": {
            "max_rounds": 2,
            "delegation_preserved": True,
        },
        "agent_outputs": public_results,
        "agent_timeline": timeline,
        "handoff": {
            "handoff_available": bool(public_results),
            "handoff_count": len(public_results),
            "handoff_refs": [
                f"worker_result:{task_id}"
                for task_id in public_results
            ],
            "safety": {
                "worker_private_tools": True,
                "coordinator_tool_visibility": "none",
                "worker_context_protocol": "main_owned",
            },
        },
        "graph_runtime": {
            "contract_version": "financial_graph_runtime.v1",
            "graph_id": graph_id,
            "task_contract": "graph_agent_task.v1",
            "result_contract": "graph_worker_result.v1",
            "focus_refs": [ref.to_dict() for ref in focus_refs],
            "resolution_audit": resolution_audit,
            "planner": plan_meta,
            "legacy_public_protocol_enabled": False,
        },
    }


__all__ = ["assemble_main_result"]

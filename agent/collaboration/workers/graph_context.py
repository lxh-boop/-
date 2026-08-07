"""Execute W08 non-trading database-write tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphRef, refs_from
from agent.tool_runtime import ToolExecutor
from agent.worker_tools import (
    DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT,
    DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
)

from ..models import GraphAgentTask, GraphWorkerResult, MemoryUpdate, MissingContextItem, ResultStatus
from .common import contract_output_slots, safe_public_value


def _tool_context(task: GraphAgentTask, output_dir: str | Path, db_path: str | Path | None) -> dict[str, Any]:
    return {
        "user_id": task.user_id,
        "conversation_id": task.session_id,
        "session_id": task.session_id,
        "run_id": task.run_id,
        "task_id": task.task_id,
        "agent_role": task.assigned_agent,
        "output_dir": output_dir,
        "db_path": db_path,
    }


def _payload_for_role(resolved_inputs: dict[str, Any] | None, role: str) -> dict[str, Any]:
    value = dict(resolved_inputs or {}).get(role)
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return {}
    payload = value.get("payload", value.get("data"))
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _missing(task: GraphAgentTask, output_type: str, role: str, description: str) -> GraphWorkerResult:
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.NEED_CONTEXT,
        output_type=output_type,
        payload=None,
        data=None,
        error=None,
        focus_refs=task.focus_refs,
        summary=description,
        missing_items=[
            MissingContextItem(
                key=role,
                description=description,
                expected_format="声明的上游强类型 WorkerResult",
                searched_sources=["declared upstream inputs"],
            )
        ],
    )


def run_graph_context(
    tool_executor: ToolExecutor,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
    *,
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    output_slots = set(contract_output_slots(task))
    if "portfolio_graph_context" in output_slots:
        portfolio_state = _payload_for_role(resolved_inputs, "current_portfolio_state")
        if not portfolio_state:
            return _missing(
                task,
                "PortfolioGraphContextResult",
                "portfolio_state",
                "缺少需要写入数据库的权威组合状态。",
            )
        tool_result = tool_executor.execute(
            DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
            {
                "portfolio_state": portfolio_state,
                "user_id": task.user_id,
                "as_of_time": task.as_of_time,
            },
            context=_tool_context(task, output_dir, db_path),
            agent_type=task.assigned_agent,
        )
        raw = dict(tool_result.data or {})
        if not tool_result.success:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                output_type="PortfolioGraphContextResult",
                data=None,
                error={
                    "code": tool_result.error_type or "portfolio_graph_write_failed",
                    "message": tool_result.error_message or tool_result.message,
                    "component": tool_result.tool_name,
                    "retryable": True,
                },
                focus_refs=task.focus_refs,
                summary="组合图上下文写入数据库失败。",
            )
        portfolio_ref_raw = raw.get("portfolio_ref")
        if not isinstance(portfolio_ref_raw, dict):
            raise ValueError("portfolio_ref_missing_after_database_write")
        portfolio_ref = GraphRef.from_dict(portfolio_ref_raw)
        holding_refs = refs_from(raw.get("holding_refs") or [])
        source_task_ids = task.input_task_ids("current_portfolio_state")
        payload = {
            "portfolio_ref": portfolio_ref.to_dict(),
            "holding_refs": [ref.to_dict() for ref in holding_refs],
            "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
            "write_summary": safe_public_value(raw.get("graph_write") or {}),
            "source_task_ids": source_task_ids,
        }
        produced_refs = [portfolio_ref, *holding_refs]
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PARTIAL if raw.get("unresolved_positions") else ResultStatus.COMPLETED,
            output_type="PortfolioGraphContextResult",
            payload_schema="portfolio_graph_context_result.v1",
            payload=payload,
            data=payload,
            error=None,
            focus_refs=[portfolio_ref],
            summary="已将组合图上下文写入数据库。",
            confidence=1.0 if not raw.get("unresolved_positions") else 0.75,
            warnings=["portfolio_contains_unresolved_positions"] if raw.get("unresolved_positions") else [],
            memory_updates=[
                MemoryUpdate(
                    key="active_graph_refs",
                    value=[ref.to_dict() for ref in produced_refs],
                    value_type="graph_ref_list",
                    source_ref=task.task_id,
                    confirmed=True,
                    confidence=1.0,
                    summary="数据库写入后生成的组合图引用。",
                )
            ],
            metadata={"produced_refs": [ref.to_dict() for ref in produced_refs], "database_write": True},
        )

    if "evidence_graph_context" in output_slots:
        collection = _payload_for_role(resolved_inputs, "entity_external_evidence")
        if not collection:
            return _missing(
                task,
                "EvidenceGraphContextResult",
                "evidence_collection",
                "缺少需要写入数据库的外部证据集合。",
            )
        tool_result = tool_executor.execute(
            DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT,
            {"evidence_collection": collection},
            context=_tool_context(task, output_dir, db_path),
            agent_type=task.assigned_agent,
        )
        raw = dict(tool_result.data or {})
        evidence_refs = refs_from(raw.get("evidence_refs") or [])
        success = bool(tool_result.success)
        payload = {
            "evidence_refs": [ref.to_dict() for ref in evidence_refs],
            "written_record_count": int(raw.get("written_record_count") or 0),
            "failed_record_count": int(raw.get("failed_record_count") or 0),
            "write_results": safe_public_value(raw.get("ingestion_results") or []),
            "source_task_ids": task.input_task_ids("entity_external_evidence"),
        }
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=(
                ResultStatus.COMPLETED
                if success and not payload["failed_record_count"]
                else ResultStatus.PARTIAL
                if evidence_refs
                else ResultStatus.FAILED
            ),
            output_type="EvidenceGraphContextResult",
            payload_schema="evidence_graph_context_result.v1",
            payload=payload if evidence_refs or success else None,
            data=payload if evidence_refs or success else None,
            error=(
                None
                if evidence_refs or success
                else {
                    "code": tool_result.error_type or "evidence_graph_write_failed",
                    "message": tool_result.error_message or tool_result.message,
                    "component": tool_result.tool_name,
                    "retryable": True,
                }
            ),
            focus_refs=evidence_refs,
            evidence_refs=evidence_refs,
            summary=f"已将 {payload['written_record_count']} 条证据写入数据库。" if evidence_refs or success else "证据图上下文写入数据库失败。",
            confidence=1.0 if success and not payload["failed_record_count"] else 0.7 if evidence_refs else 0.0,
            warnings=["partial_evidence_graph_write"] if payload["failed_record_count"] else [],
            metadata={"produced_refs": [ref.to_dict() for ref in evidence_refs], "database_write": True},
        )

    raise ValueError(f"unsupported_database_write_contract:{sorted(output_slots)}")


__all__ = ["run_graph_context"]

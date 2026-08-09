"""Execute W08 non-trading database-write tasks.

W08 selects the concrete graph-write operation from Runtime-materialized input
semantics, not from legacy output-slot names. Successful results are published
only through ``data["slots"]``.
"""

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
from .common import materialize_promised_slots, safe_public_value


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


def _direct_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    return dict(value) if isinstance(value, dict) else {}


def _select_write_input(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]]:
    """Return ``(kind, slot_id, value)`` from materialized runtime inputs."""

    resolved = dict(resolved_inputs or {})
    explicit_kind = str(task.args.get("graph_context_kind") or "").strip().lower()
    evidence: list[tuple[str, dict[str, Any]]] = []
    portfolio: list[tuple[str, dict[str, Any]]] = []
    for slot_id, raw in resolved.items():
        value = _direct_dict(raw)
        if not value:
            continue
        semantic = str(slot_id).lower()
        if "evidence" in semantic:
            evidence.append((str(slot_id), value))
        if any(token in semantic for token in ("portfolio", "position")):
            portfolio.append((str(slot_id), value))

    if explicit_kind in {"evidence", "evidence_graph_context"} and evidence:
        return "evidence", evidence[0][0], evidence[0][1]
    if explicit_kind in {"portfolio", "portfolio_graph_context"} and portfolio:
        return "portfolio", portfolio[0][0], portfolio[0][1]
    if evidence and not portfolio:
        return "evidence", evidence[0][0], evidence[0][1]
    if portfolio and not evidence:
        return "portfolio", portfolio[0][0], portfolio[0][1]
    if evidence and portfolio:
        raise ValueError("graph_context_write_input_ambiguous")
    return "", "", {}


def _missing(task: GraphAgentTask, role: str, description: str) -> GraphWorkerResult:
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.NEED_CONTEXT,
        output_type="GraphContextResult",
        data=None,
        error=None,
        focus_refs=task.focus_refs,
        summary=description,
        missing_items=[MissingContextItem(
            key=role,
            description=description,
            expected_format="Runtime materialized semantic slot",
            searched_sources=["RunSlotStore", "resolved_input_bindings"],
        )],
    )


def run_graph_context(
    tool_executor: ToolExecutor,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
    *,
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    kind, source_slot_id, source_value = _select_write_input(task, resolved_inputs)
    if not source_value:
        return _missing(task, "graph_context_input", "缺少可写入图上下文的权威结构化输入。")

    if kind == "portfolio":
        tool_result = tool_executor.execute(
            DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
            {"portfolio_state": source_value, "user_id": task.user_id, "as_of_time": task.as_of_time},
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
        payload = {
            "portfolio_ref": portfolio_ref.to_dict(),
            "holding_refs": [ref.to_dict() for ref in holding_refs],
            "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
            "write_summary": safe_public_value(raw.get("graph_write") or {}),
            "source_slot_id": source_slot_id,
            "source_task_ids": task.input_task_ids(source_slot_id),
        }
        slots = materialize_promised_slots(task, payload)
        produced_refs = [portfolio_ref, *holding_refs]
        partial = bool(raw.get("unresolved_positions"))
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PARTIAL if partial else ResultStatus.COMPLETED,
            output_type="PortfolioGraphContextResult",
            data={**payload, "slots": slots},
            error=None,
            focus_refs=[portfolio_ref],
            summary="已将组合图上下文写入数据库。",
            confidence=0.75 if partial else 1.0,
            warnings=["portfolio_contains_unresolved_positions"] if partial else [],
            memory_updates=[MemoryUpdate(
                key="active_graph_refs",
                value=[ref.to_dict() for ref in produced_refs],
                value_type="graph_ref_list",
                source_ref=task.task_id,
                confirmed=True,
                confidence=1.0,
                summary="数据库写入后生成的组合图引用。",
            )],
            metadata={"produced_refs": [ref.to_dict() for ref in produced_refs], "database_write": True},
        )

    if kind == "evidence":
        tool_result = tool_executor.execute(
            DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT,
            {"evidence_collection": source_value},
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
            "source_slot_id": source_slot_id,
            "source_task_ids": task.input_task_ids(source_slot_id),
        }
        slots = materialize_promised_slots(task, payload) if evidence_refs or success else {}
        status = (
            ResultStatus.COMPLETED
            if success and not payload["failed_record_count"]
            else ResultStatus.PARTIAL
            if evidence_refs
            else ResultStatus.FAILED
        )
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=status,
            output_type="EvidenceGraphContextResult",
            data={**payload, "slots": slots} if evidence_refs or success else None,
            error=(None if evidence_refs or success else {
                "code": tool_result.error_type or "evidence_graph_write_failed",
                "message": tool_result.error_message or tool_result.message,
                "component": tool_result.tool_name,
                "retryable": True,
            }),
            focus_refs=evidence_refs,
            evidence_refs=evidence_refs,
            summary=(f"已将 {payload['written_record_count']} 条证据写入数据库。" if evidence_refs or success else "证据图上下文写入数据库失败。"),
            confidence=1.0 if status == ResultStatus.COMPLETED else 0.7 if evidence_refs else 0.0,
            warnings=["partial_evidence_graph_write"] if payload["failed_record_count"] else [],
            metadata={"produced_refs": [ref.to_dict() for ref in evidence_refs], "database_write": True},
        )

    raise ValueError(f"unsupported_database_write_input:{kind}")


__all__ = ["run_graph_context"]

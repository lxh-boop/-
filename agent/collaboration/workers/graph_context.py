"""Execute W08 non-trading graph-context writes from the current ContextBundle."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphRef, refs_from
from agent.tool_runtime import ToolExecutor
from agent.worker_tools import DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT, DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT

from ..models import GraphAgentTask, GraphWorkerResult, MemoryUpdate, MissingContextItem, ResultStatus
from .common import materialize_promised_data, safe_public_value


def _tool_context(task: GraphAgentTask, output_dir: str | Path, db_path: str | Path | None) -> dict[str, Any]:
    return {"user_id": task.user_id, "conversation_id": task.session_id, "session_id": task.session_id,
            "run_id": task.run_id, "task_id": task.task_id, "agent_role": task.assigned_agent,
            "output_dir": output_dir, "db_path": db_path}


def _flatten(context: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = dict((context or {}).get("global_data") or {})
    for entity in (context or {}).get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for name, value in dict(entity.get("data") or {}).items():
            out.setdefault(str(name), value)
    return out


def _select_write_input(task: GraphAgentTask, context: dict[str, Any] | None) -> tuple[str, str, Any]:
    data = _flatten(context)
    explicit = str(task.args.get("graph_context_kind") or "").strip().lower()
    evidence = [(name, value) for name, value in data.items() if "evidence" in name]
    portfolio = [(name, value) for name, value in data.items() if any(token in name for token in ("portfolio", "position"))]
    if explicit in {"evidence", "evidence_graph_context"} and evidence:
        return "evidence", evidence[0][0], evidence[0][1]
    if explicit in {"portfolio", "portfolio_graph_context"} and portfolio:
        return "portfolio", portfolio[0][0], portfolio[0][1]
    if evidence and not portfolio:
        return "evidence", evidence[0][0], evidence[0][1]
    if portfolio and not evidence:
        return "portfolio", portfolio[0][0], portfolio[0][1]
    if evidence and portfolio:
        raise ValueError("graph_context_write_input_ambiguous")
    return "", "", None


def _missing(task: GraphAgentTask, description: str) -> GraphWorkerResult:
    return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.NEED_CONTEXT,
        output_type="GraphContextResult", data=None, error=None, focus_refs=task.focus_refs, summary=description,
        missing_items=[MissingContextItem(key="graph_context_input", description=description,
            expected_format="ContextBundle business data", searched_sources=["ContextBundle"])])


def run_graph_context(tool_executor: ToolExecutor, task: GraphAgentTask, output_dir: str | Path,
                      db_path: str | Path | None, *, working_memory_context: dict[str, Any] | None = None) -> GraphWorkerResult:
    kind, source_name, source_value = _select_write_input(task, working_memory_context)
    if source_value is None:
        return _missing(task, "缺少可写入图上下文的已验证工作记忆数据。")

    if kind == "portfolio":
        tr = tool_executor.execute(DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
            {"portfolio_state": source_value, "user_id": task.user_id, "as_of_time": task.as_of_time},
            context=_tool_context(task, output_dir, db_path), agent_type=task.assigned_agent)
        raw = dict(tr.data or {})
        if not tr.success:
            return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.FAILED,
                output_type="PortfolioGraphContextResult", data=None,
                error={"code": tr.error_type or "portfolio_graph_write_failed", "message": tr.error_message or tr.message,
                       "component": tr.tool_name, "retryable": True}, focus_refs=task.focus_refs, summary="组合图上下文写入失败。")
        portfolio_ref = GraphRef.from_dict(dict(raw.get("portfolio_ref") or {}))
        holdings = refs_from(raw.get("holding_refs") or [])
        payload = {"portfolio_ref": portfolio_ref.to_dict(), "holding_refs": [r.to_dict() for r in holdings],
                   "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
                   "write_summary": safe_public_value(raw.get("graph_write") or {}), "source_data_name": source_name}
        business_data = materialize_promised_data(task, payload)
        partial = bool(raw.get("unresolved_positions"))
        return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent,
            status=ResultStatus.PARTIAL if partial else ResultStatus.COMPLETED, output_type="PortfolioGraphContextResult",
            data={**payload, "business_data": business_data, "produced_data_names": list(business_data)}, error=None,
            focus_refs=[portfolio_ref], summary="已将组合图上下文写入数据库。", confidence=0.75 if partial else 1.0,
            warnings=["portfolio_contains_unresolved_positions"] if partial else [],
            memory_updates=[MemoryUpdate(key="active_graph_refs", value=[r.to_dict() for r in [portfolio_ref, *holdings]],
                value_type="graph_ref_list", source_ref=task.task_id, confirmed=True, confidence=1.0,
                summary="数据库写入后生成的组合图引用。")], metadata={"database_write": True})

    if kind == "evidence":
        tr = tool_executor.execute(DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT, {"evidence_collection": source_value},
            context=_tool_context(task, output_dir, db_path), agent_type=task.assigned_agent)
        raw = dict(tr.data or {})
        refs = refs_from(raw.get("evidence_refs") or [])
        payload = {"evidence_refs": [r.to_dict() for r in refs], "written_record_count": int(raw.get("written_record_count") or 0),
                   "failed_record_count": int(raw.get("failed_record_count") or 0),
                   "write_results": safe_public_value(raw.get("ingestion_results") or []), "source_data_name": source_name}
        success = bool(tr.success)
        status = ResultStatus.COMPLETED if success and not payload["failed_record_count"] else ResultStatus.PARTIAL if refs else ResultStatus.FAILED
        business_data = materialize_promised_data(task, payload) if success or refs else {}
        return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent, status=status,
            output_type="EvidenceGraphContextResult", data=({**payload, "business_data": business_data,
            "produced_data_names": list(business_data)} if success or refs else None),
            error=None if success or refs else {"code": tr.error_type or "evidence_graph_write_failed",
                "message": tr.error_message or tr.message, "component": tr.tool_name, "retryable": True},
            focus_refs=refs, evidence_refs=refs, summary=f"已将 {payload['written_record_count']} 条证据写入数据库。" if success or refs else "证据图上下文写入失败。",
            confidence=1.0 if status == ResultStatus.COMPLETED else 0.7 if refs else 0.0,
            warnings=["partial_evidence_graph_write"] if payload["failed_record_count"] else [], metadata={"database_write": True})
    raise ValueError(f"unsupported_database_write_input:{kind}")

__all__ = ["run_graph_context"]

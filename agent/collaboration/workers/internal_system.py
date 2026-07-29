"""Execute W02 task-specific internal system data queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphRef, refs_from
from agent.tool_runtime import ToolExecutor
from agent.worker_tools import (
    INTERNAL_ACCOUNT_GET_STATE,
    INTERNAL_BACKTEST_GET_SUMMARY,
    INTERNAL_MODEL_GET_METRICS,
    INTERNAL_PORTFOLIO_GET_STATE,
    INTERNAL_PREDICTION_GET_STOCK,
    INTERNAL_RANKING_GET_LATEST,
    INTERNAL_STRATEGY_GET_SELECTED,
    INTERNAL_USER_PROFILE_GET,
)

from ..models import GraphAgentTask, GraphWorkerResult, MemoryUpdate, ResultStatus
from .common import safe_public_value


_TASK_TO_TOOL_OUTPUT = {
    "query_stock_prediction": (INTERNAL_PREDICTION_GET_STOCK, "ModelPredictionResult"),
    "query_latest_ranking": (INTERNAL_RANKING_GET_LATEST, "RankingResult"),
    "query_model_metrics": (INTERNAL_MODEL_GET_METRICS, "ModelMetricsResult"),
    "query_backtest_summary": (INTERNAL_BACKTEST_GET_SUMMARY, "BacktestSummaryResult"),
    "query_selected_strategy": (INTERNAL_STRATEGY_GET_SELECTED, "SelectedStrategyResult"),
    "query_account_state": (INTERNAL_ACCOUNT_GET_STATE, "AccountStateResult"),
    "query_user_profile": (INTERNAL_USER_PROFILE_GET, "UserProfileResult"),
}
_PORTFOLIO_TASKS = {
    "query_portfolio_state",
    "load_portfolio_snapshot",
    "analyze_portfolio",
    "analyze_portfolio_fit",
    "compare_portfolios",
    "resolve_context",
}


def _tool_context(
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> dict[str, Any]:
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


def _artifact_refs(tool_result: Any) -> list[dict[str, Any]]:
    artifact_id = str(getattr(tool_result, "artifact_id", "") or "")
    return [{"artifact_id": artifact_id}] if artifact_id else []


def _run_portfolio_query(
    tool_executor: ToolExecutor,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> GraphWorkerResult:
    tool_result = tool_executor.execute(
        INTERNAL_PORTFOLIO_GET_STATE,
        {"user_id": task.user_id, "as_of_time": task.as_of_time},
        context=_tool_context(task, output_dir, db_path),
        agent_type=task.assigned_agent,
    )
    raw = dict(tool_result.data or {})
    if not tool_result.success:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            output_type="PortfolioAnalysisResult",
            payload_schema="portfolio_analysis_result.v1",
            payload=None,
            data=None,
            error={
                "code": tool_result.error_type or str(raw.get("error_type") or "portfolio_dependency_failed"),
                "message": tool_result.error_message or str(raw.get("message") or tool_result.message or "无法读取当前组合。"),
                "component": tool_result.tool_name,
                "retryable": True,
            },
            focus_refs=task.focus_refs,
            summary=str(raw.get("message") or tool_result.message or "无法读取当前组合。"),
            warnings=[*tool_result.warnings, *[str(item) for item in raw.get("warnings") or []]],
            artifact_refs=_artifact_refs(tool_result),
        )
    portfolio_ref = GraphRef.from_dict(dict(raw["portfolio_ref"]))
    holding_refs = refs_from(raw.get("holding_refs") or [])
    produced = [portfolio_ref, *holding_refs]
    payload = {
        "portfolio_ref": portfolio_ref.to_dict(),
        "holding_refs": [ref.to_dict() for ref in holding_refs],
        "portfolio_summary": safe_public_value(raw.get("portfolio") or {}),
        "unresolved_positions": safe_public_value(raw.get("unresolved_positions") or []),
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.PARTIAL if raw.get("unresolved_positions") else ResultStatus.COMPLETED,
        output_type="PortfolioAnalysisResult",
        payload_schema="portfolio_analysis_result.v1",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=[portfolio_ref],
        summary="已读取当前组合，并生成 Neo4j 组合快照。",
        findings=[{
            "kind": "portfolio_snapshot",
            "portfolio_ref": portfolio_ref.to_dict(),
            "holding_refs": [ref.to_dict() for ref in holding_refs],
            "holding_count": len(holding_refs),
            "unresolved_position_count": len(raw.get("unresolved_positions") or []),
        }],
        confidence=1.0 if not raw.get("unresolved_positions") else 0.75,
        warnings=["portfolio_contains_unresolved_positions"] if raw.get("unresolved_positions") else [],
        artifact_refs=_artifact_refs(tool_result),
        memory_updates=[MemoryUpdate(
            key="active_graph_refs",
            value=[ref.to_dict() for ref in produced],
            value_type="graph_ref_list",
            source_ref=task.task_id,
            confirmed=True,
            confidence=1.0,
            summary="当前组合快照及持仓对象引用。",
        )],
        metadata={
            "produced_refs": [ref.to_dict() for ref in produced],
            "tool_execution": {"tool_name": tool_result.tool_name, "artifact_id": tool_result.artifact_id},
        },
    )


def run_internal_system(
    tool_executor: ToolExecutor,
    task: GraphAgentTask,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
) -> GraphWorkerResult:
    """Run exactly the private read capability declared by W02 task_type."""

    if task.task_type in _PORTFOLIO_TASKS:
        return _run_portfolio_query(tool_executor, task, output_dir, db_path)
    mapping = _TASK_TO_TOOL_OUTPUT.get(task.task_type)
    if mapping is None:
        raise ValueError(f"unsupported_internal_system_task:{task.task_type}")
    tool_name, output_type = mapping
    arguments = dict(task.args or {})
    if task.task_type == "query_stock_prediction":
        selected_ids = {str(item) for item in task.args.get("focus_ref_ids") or []}
        selected = next(
            (ref for ref in [*task.focus_refs, *task.context_refs] if not selected_ids or ref.node_id in selected_ids),
            None,
        )
        if selected is None:
            raise ValueError("authoritative_security_graph_ref_required")
        arguments = {
            "security_node_id": selected.node_id,
            "top_k": int(task.args.get("top_k") or default_top_k or 10),
            "model_name": str(task.args.get("model_name") or ""),
            "trade_date": str(task.args.get("trade_date") or ""),
        }
    elif task.task_type in {"query_account_state", "query_user_profile"}:
        arguments["user_id"] = task.user_id
    tool_result = tool_executor.execute(
        tool_name,
        arguments,
        context=_tool_context(task, output_dir, db_path),
        agent_type=task.assigned_agent,
    )
    payload = safe_public_value(tool_result.data or {})
    if task.task_type == "query_stock_prediction":
        selected = next(iter(task.focus_refs), None)
        payload = dict(payload or {})
        payload["security_ref"] = selected.to_dict() if selected else {}
    success = bool(tool_result.success)
    status = ResultStatus.COMPLETED if success else ResultStatus.FAILED
    summary_by_type = {
        "ModelPredictionResult": "已查询该证券的最新模型预测结果。",
        "RankingResult": "已查询系统最新预测排名。",
        "ModelMetricsResult": "已查询当前模型指标。",
        "BacktestSummaryResult": "已查询模型或策略回测摘要。",
        "SelectedStrategyResult": "已查询当前选定策略。",
        "AccountStateResult": "已查询当前账户资金状态。",
        "UserProfileResult": "已查询当前用户画像。",
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=status,
        output_type=output_type,
        payload_schema=f"{output_type}.v1",
        payload=payload if success else None,
        data=payload if success else None,
        error=None if success else {
            "code": tool_result.error_type or "internal_system_data_unavailable",
            "message": tool_result.error_message or tool_result.message,
            "component": tool_result.tool_name,
            "retryable": True,
        },
        focus_refs=task.focus_refs,
        summary=summary_by_type.get(output_type, tool_result.message) if success else str(tool_result.message or "内部数据查询失败。"),
        findings=[{
            "kind": "internal_system_query",
            "output_type": output_type,
            "found": bool((payload or {}).get("found", True)) if isinstance(payload, dict) else success,
            "source_id": str((payload or {}).get("source_id") or "") if isinstance(payload, dict) else "",
        }] if success else [],
        confidence=1.0 if success else 0.0,
        warnings=[*tool_result.warnings, *tool_result.errors],
        artifact_refs=_artifact_refs(tool_result),
        metadata={
            "tool_execution": {
                "tool_name": tool_result.tool_name,
                "artifact_id": tool_result.artifact_id,
                "error_type": tool_result.error_type,
            }
        },
    )


__all__ = ["run_internal_system"]

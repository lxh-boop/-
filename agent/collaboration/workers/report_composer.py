"""Generate the final report from sanitized upstream Worker results.

The report composer receives only ``GraphWorkerResult`` contracts and uses the
run-scoped LLM service for synthesis. It does not query providers, re-read raw
evidence, resolve entities, call business tools, or mutate state.
"""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from agent.graph.contracts import GraphNodeKind, GraphPathRef

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import dependency_results as dependency_result_items
from .common import refs_from_dependencies, safe_public_value


def run_report_composer(
    llm_service: LLMService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    language: str,
) -> GraphWorkerResult:
    safe_results = [
        {
            "contract_version": str(
                item.get("contract_version") or "graph_worker_result.v1"
            ),
            "task_id": str(item.get("task_id") or ""),
            "agent_id": str(item.get("agent_id") or ""),
            "status": str(item.get("status") or ""),
            "focus_refs": safe_public_value(item.get("focus_refs") or []),
            "summary": str(item.get("summary") or "")[:2000],
            "findings": safe_public_value(item.get("findings") or []),
            "recommendations": safe_public_value(item.get("recommendations") or []),
            "evidence_refs": safe_public_value(item.get("evidence_refs") or []),
            "graph_path_refs": safe_public_value(item.get("graph_path_refs") or []),
            "warnings": safe_public_value(item.get("warnings") or []),
            "missing_items": safe_public_value(item.get("missing_items") or []),
            "confidence": item.get("confidence"),
        }
        for item in dependency_result_items(dependency_results)
    ]
    if not safe_results:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="报告生成缺少上游 GraphWorkerResult。",
            missing_items=[
                MissingContextItem(
                    key="worker_results",
                    description="需要上游专业 Worker 的标准结果。",
                    searched_sources=["dependency_results"],
                )
            ],
        )
    system = (
        "你是金融 Agent 的 Report Composer。你只能使用输入中的 GraphWorkerResult，不能重新解析原始新闻正文，"
        "不能猜证券代码，不能引用未提供的实体、证据或影响路径。明确区分已验证事实、来源声明、间接关系和不确定性。"
        "若没有影响路径，必须明确说当前证据不足，不能把新闻提及当作因果影响。"
        "不要暴露内部 Agent 名称、task_id、GraphRef 技术字段、工具名或数据库实现。"
        "使用中文回答。"
        if language != "en"
        else (
            "You are the financial Agent report composer. Use only the supplied "
            "GraphWorkerResult contracts. Do not re-parse raw evidence or invent "
            "entity identities, evidence, or causal paths. Clearly separate "
            "validated facts, claims, indirect relations, and uncertainty. Do not "
            "expose internal agents, task IDs, tools, GraphRef fields, or storage details."
        )
    )
    answer = llm_service.generate_text(
        stage="graph_report_composer",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "objective": task.objective,
                        "worker_results": safe_results,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=3000,
        operation="compose_graph_grounded_report",
    )
    statuses = {str(item.get("status") or "") for item in safe_results}
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.PARTIAL
            if statuses & {"partial", "need_context", "failed"}
            else ResultStatus.COMPLETED
        ),
        focus_refs=task.focus_refs,
        summary=str(answer or ""),
        findings=[{"kind": "report", "text": str(answer or "")}],
        confidence=min(
            [float(item.get("confidence") or 0.0) for item in safe_results] or [0.0]
        ),
        evidence_refs=refs_from_dependencies(
            dependency_results,
            kinds={GraphNodeKind.EVIDENCE},
        ),
        graph_path_refs=[
            GraphPathRef(**path)
            for item in safe_results
            for path in item.get("graph_path_refs") or []
            if isinstance(path, dict)
        ],
    )

"""Execute portfolio-impact path analysis from upstream graph results.

The executor requires a cause/evidence anchor and a portfolio snapshot reference,
then queries validated graph paths. It does not retrieve evidence, load portfolio
state, infer missing identities, or create portfolio changes.
"""

from __future__ import annotations

from typing import Any

from agent.graph.contracts import GraphNodeKind, refs_from
from agent.graph.impact_service import GraphImpactService

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import refs_from_dependencies, safe_public_value


def run_graph_impact(
    impact_service: GraphImpactService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
) -> GraphWorkerResult:
    source_task_ids = [
        str(item) for item in task.args.get("source_task_ids") or []
    ]
    target_task_ids = [
        str(item) for item in task.args.get("target_task_ids") or []
    ]
    selected_dependencies = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not source_task_ids + target_task_ids
        or task_id in set(source_task_ids + target_task_ids)
    }
    causes = [
        ref
        for ref in task.focus_refs + task.context_refs
        if ref.node_kind in {GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION}
        or (
            ref.node_kind == GraphNodeKind.OBJECT
            and ref.role in {"cause", "focus", "event"}
        )
    ]
    causes.extend(
        refs_from_dependencies(
            selected_dependencies,
            kinds={GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION},
        )
    )
    causes = refs_from([ref.to_dict() for ref in causes])
    portfolio_candidates = [
        ref
        for ref in task.focus_refs + task.context_refs
        if ref.node_kind == GraphNodeKind.OBJECT
        and ref.role in {"impact_target", "portfolio", "focus"}
        and "portfolio" in ref.node_id.lower()
    ]
    portfolio_candidates.extend(
        refs_from_dependencies(selected_dependencies, kinds={GraphNodeKind.OBJECT})
    )
    portfolio_ref = next(
        (ref for ref in portfolio_candidates if "portfolio" in ref.node_id.lower()),
        None,
    )
    missing: list[MissingContextItem] = []
    if not causes:
        missing.append(
            MissingContextItem(
                key="cause_graph_ref",
                description="缺少新闻、事件或声明原因锚点。",
                expected_format="Evidence/Assertion/Event GraphRef",
                searched_sources=["task refs", "dependency results"],
            )
        )
    if portfolio_ref is None:
        missing.append(
            MissingContextItem(
                key="portfolio_snapshot_ref",
                description="缺少当前用户组合快照。",
                expected_format="PortfolioSnapshot GraphRef",
                searched_sources=["task refs", "dependency results"],
            )
        )
    if missing:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="ImpactAnalysisResult",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="影响路径分析缺少必要图锚点。",
            missing_items=missing,
        )
    paths = impact_service.find_paths(
        cause_refs=causes,
        portfolio_ref=portfolio_ref,
        as_of_time=task.as_of_time,
    )
    summary = impact_service.summarize_paths(paths)
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED if paths else ResultStatus.PARTIAL,
        output_type="ImpactAnalysisResult",
        data={
            "source_task_ids": source_task_ids or list(selected_dependencies.keys()),
            "target_task_ids": target_task_ids or list(selected_dependencies.keys()),
            "impact_paths": [path.to_dict() for path in paths],
            "impact_summary": safe_public_value(summary),
        },
        error=None,
        focus_refs=[*causes, portfolio_ref],
        summary=(
            f"已找到 {len(paths)} 条可追踪影响路径，涉及 {summary.get('holding_count', 0)} 个持仓。"
            if paths
            else "当前权威图和证据图中未找到新闻到持仓的可验证路径。"
        ),
        findings=[{"kind": "portfolio_impact_paths", **safe_public_value(summary)}],
        graph_path_refs=paths,
        evidence_refs=[
            ref for ref in causes if ref.node_kind == GraphNodeKind.EVIDENCE
        ],
        confidence=max((path.confidence for path in paths), default=0.0),
        warnings=[] if paths else ["no_validated_impact_path"],
        metadata={"produced_refs": [portfolio_ref.to_dict()]},
    )

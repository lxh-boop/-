from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.graph.contracts import GraphNodeKind, GraphPatch, GraphPathRef, GraphRef, refs_from
from agent.graph.impact_service import GraphImpactService
from agent.graph.provider_adapter import GraphProviderAdapter

from .agent_directory import (
    EVIDENCE_RETRIEVER,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from .models import (
    GraphAgentTask,
    GraphWorkerResult,
    MemoryUpdate,
    MissingContextItem,
    ResultStatus,
    TaskStatus,
)

_BLOCKED_PUBLIC_KEYS = {
    "stock_code", "stock_codes", "stock_name", "ts_code", "symbol", "security_scope",
    "raw_payload", "raw_tool_payload", "tool_calls", "arguments", "sql", "cypher",
    "confirmation_token", "confirmation_token_hash", "api_key", "password", "secret",
    "private_chain_of_thought", "chain_of_thought", "reasoning_content",
}


def _safe(value: Any, *, depth: int = 0, max_depth: int = 5, max_items: int = 40) -> Any:
    if depth >= max_depth:
        return "<summarized>" if isinstance(value, (dict, list, tuple, set)) else str(value)[:1000]
    if isinstance(value, dict):
        return {
            str(key): _safe(item, depth=depth + 1, max_depth=max_depth, max_items=max_items)
            for key, item in list(value.items())[:max_items]
            if str(key).lower() not in _BLOCKED_PUBLIC_KEYS
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe(item, depth=depth + 1, max_depth=max_depth, max_items=max_items) for item in list(value)[:max_items]]
    if isinstance(value, str):
        return value[:3000] + ("…" if len(value) > 3000 else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _safe(value.to_dict(), depth=depth, max_depth=max_depth, max_items=max_items)
    return str(value)[:1000]


def _dependency_results(value: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in value.values() if isinstance(item, dict)]


def _refs_from_dependencies(
    dependency_results: dict[str, dict[str, Any]],
    *,
    roles: set[str] | None = None,
    kinds: set[GraphNodeKind] | None = None,
) -> list[GraphRef]:
    refs: list[GraphRef] = []
    for payload in dependency_results.values():
        if not isinstance(payload, dict):
            continue
        candidates = []
        candidates.extend(payload.get("focus_refs") or [])
        candidates.extend(payload.get("evidence_refs") or [])
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        candidates.extend(metadata.get("produced_refs") or [])
        for ref in refs_from(candidates):
            if roles and ref.role not in roles:
                continue
            if kinds and ref.node_kind not in kinds:
                continue
            if not any(existing.node_id == ref.node_id and existing.role == ref.role for existing in refs):
                refs.append(ref)
    return refs


class SpecialistRuntime:
    """Execute one Worker task behind a GraphRef-only public boundary."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        provider: GraphProviderAdapter,
        impact_service: GraphImpactService,
    ) -> None:
        self.llm_service = llm_service
        self.provider = provider
        self.impact_service = impact_service

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
    ) -> GraphWorkerResult:
        started = time.perf_counter()
        task.status = TaskStatus.RUNNING
        try:
            if task.assigned_agent == EVIDENCE_RETRIEVER:
                result = self._run_evidence(task, current_user_request, output_dir, db_path, default_top_k)
            elif task.assigned_agent == PORTFOLIO_ANALYST:
                result = self._run_portfolio(task, output_dir, db_path)
            elif task.assigned_agent == GRAPH_IMPACT_ANALYST:
                result = self._run_graph_impact(task, dependency_results)
            elif task.assigned_agent == RISK_ANALYST:
                result = self._run_risk(task, dependency_results, output_dir, db_path)
            elif task.assigned_agent == STRATEGY_GUARD:
                result = self._run_strategy_guard(
                    task,
                    current_user_request=current_user_request,
                    dependency_results=dependency_results,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    language=language,
                    execution_context=execution_context,
                )
            elif task.assigned_agent == REPORT_WRITER:
                result = self._run_report_writer(task, dependency_results, language)
            elif task.assigned_agent == SYSTEM_DIAGNOSTIC:
                result = self._run_diagnostic(task)
            else:
                result = GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.NOT_EXECUTED,
                    focus_refs=task.focus_refs,
                    summary=f"Unsupported Worker agent: {task.assigned_agent}",
                    warnings=["unknown_worker_agent"],
                )
        except Exception as exc:
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                focus_refs=task.focus_refs,
                summary=(
                    "金融图或专业数据链路执行失败。"
                    if language != "en"
                    else "The financial-graph or specialist data path failed."
                ),
                warnings=[f"{type(exc).__name__}:{exc}"],
                metadata={"error_type": type(exc).__name__},
            )
        result.metadata.setdefault("task_type", task.task_type)
        result.metadata.setdefault("attempt", task.attempt)
        result.metadata.setdefault("duration_ms", round((time.perf_counter() - started) * 1000, 2))
        task.status = (
            TaskStatus.COMPLETED
            if result.status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
            else TaskStatus.PARTIAL
            if result.status == ResultStatus.PARTIAL
            else TaskStatus.WAITING_CONTEXT
            if result.status == ResultStatus.NEED_CONTEXT
            else TaskStatus.FAILED
        )
        return result

    def _run_evidence(
        self,
        task: GraphAgentTask,
        query: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
    ) -> GraphWorkerResult:
        evidence_refs = [ref for ref in task.focus_refs + task.context_refs if ref.node_kind == GraphNodeKind.EVIDENCE]
        object_refs = [ref for ref in task.focus_refs if ref.node_kind == GraphNodeKind.OBJECT]
        if evidence_refs and not object_refs:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.COMPLETED,
                focus_refs=task.focus_refs,
                summary="已使用指定新闻或证据节点作为分析原因锚点。",
                evidence_refs=evidence_refs,
                findings=[{"kind": "provided_evidence", "evidence_refs": [ref.to_dict() for ref in evidence_refs]}],
                confidence=1.0,
                metadata={"produced_refs": [ref.to_dict() for ref in evidence_refs]},
            )
        if not object_refs:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                focus_refs=task.focus_refs,
                summary="缺少已解析的金融对象或指定证据。",
                missing_items=[
                    MissingContextItem(
                        key="focus_graph_ref",
                        description="需要明确分析对象或指定新闻的 GraphRef。",
                        expected_format="唯一对象、新闻、公告或研报",
                        reason="Worker 不允许从自由文本重新猜测权威金融实体。",
                        searched_sources=["task.focus_refs", "task.context_refs"],
                    )
                ],
            )
        if task.task_type == "analyze_entity_evidence":
            analysis = self.provider.analyze_entities(
                object_refs,
                user_id=task.user_id,
                output_dir=output_dir,
                db_path=db_path,
            )
        else:
            analysis = self.provider.retrieve_evidence(
                object_refs,
                query=query or task.objective,
                top_k=max(1, min(int(default_top_k or 20), 100)),
                output_dir=output_dir,
                db_path=db_path,
                source_task_id=task.task_id,
                source_agent_id=task.assigned_agent,
                as_of_time=task.as_of_time,
            )
        produced_evidence = refs_from(analysis.get("evidence_refs") or [])
        success = bool(analysis.get("success"))
        findings = []
        for item in analysis.get("results") or []:
            if not isinstance(item, dict):
                continue
            findings.append(
                {
                    "kind": "entity_evidence_result",
                    "focus_ref": _safe(item.get("focus_ref")),
                    "success": bool(item.get("success")),
                    "message": str(item.get("message") or "")[:1200],
                    "record_count": len(item.get("records") or []),
                    "source_count": len(item.get("sources") or []),
                    "data_summary": _safe(item.get("data") or {}),
                }
            )
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED if success else ResultStatus.FAILED,
            focus_refs=object_refs,
            summary="已完成金融对象证据读取并写入可追踪金融图。" if success else "未获得可用的金融证据。",
            findings=findings,
            confidence=0.85 if success else 0.0,
            evidence_refs=produced_evidence,
            warnings=[str(item) for item in analysis.get("warnings") or []],
            metadata={
                "produced_refs": [ref.to_dict() for ref in produced_evidence],
                "ingestion_results": _safe(analysis.get("ingestion_results") or []),
            },
        )

    def _run_portfolio(
        self,
        task: GraphAgentTask,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> GraphWorkerResult:
        raw = self.provider.load_portfolio_snapshot(
            user_id=task.user_id,
            output_dir=output_dir,
            db_path=db_path,
            as_of_time=task.as_of_time,
            source_task_id=task.task_id,
            source_agent_id=task.assigned_agent,
        )
        if not raw.get("success"):
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                focus_refs=task.focus_refs,
                summary=str(raw.get("message") or "无法读取当前组合。"),
                warnings=[str(item) for item in raw.get("warnings") or []],
            )
        portfolio_ref = GraphRef.from_dict(dict(raw["portfolio_ref"]))
        holding_refs = refs_from(raw.get("holding_refs") or [])
        produced = [portfolio_ref, *holding_refs]
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PARTIAL if raw.get("unresolved_positions") else ResultStatus.COMPLETED,
            focus_refs=[portfolio_ref],
            summary="已读取当前组合，并生成 Neo4j 组合快照。",
            findings=[
                {
                    "kind": "portfolio_snapshot",
                    "portfolio_ref": portfolio_ref.to_dict(),
                    "holding_refs": [ref.to_dict() for ref in holding_refs],
                    "holding_count": len(holding_refs),
                    "unresolved_position_count": len(raw.get("unresolved_positions") or []),
                    "portfolio_summary": _safe(raw.get("portfolio") or {}),
                }
            ],
            confidence=1.0 if not raw.get("unresolved_positions") else 0.75,
            warnings=["portfolio_contains_unresolved_positions"] if raw.get("unresolved_positions") else [],
            memory_updates=[
                MemoryUpdate(
                    key="active_graph_refs",
                    value=[ref.to_dict() for ref in produced],
                    value_type="graph_ref_list",
                    source_ref=task.task_id,
                    confirmed=True,
                    confidence=1.0,
                    summary="当前组合快照及持仓对象引用。",
                )
            ],
            metadata={
                "produced_refs": [ref.to_dict() for ref in produced],
                "unresolved_positions": _safe(raw.get("unresolved_positions") or []),
            },
        )

    def _run_graph_impact(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
    ) -> GraphWorkerResult:
        causes = [
            ref for ref in task.focus_refs + task.context_refs
            if ref.node_kind in {GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION}
            or (ref.node_kind == GraphNodeKind.OBJECT and ref.role in {"cause", "focus", "event"})
        ]
        causes.extend(
            _refs_from_dependencies(
                dependency_results,
                kinds={GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION},
            )
        )
        causes = refs_from([ref.to_dict() for ref in causes])
        portfolio_candidates = [
            ref for ref in task.focus_refs + task.context_refs
            if ref.node_kind == GraphNodeKind.OBJECT and ref.role in {"impact_target", "portfolio", "focus"}
            and "portfolio" in ref.node_id.lower()
        ]
        portfolio_candidates.extend(
            _refs_from_dependencies(dependency_results, kinds={GraphNodeKind.OBJECT})
        )
        portfolio_ref = next((ref for ref in portfolio_candidates if "portfolio" in ref.node_id.lower()), None)
        missing: list[MissingContextItem] = []
        if not causes:
            missing.append(MissingContextItem(
                key="cause_graph_ref",
                description="缺少新闻、事件或声明原因锚点。",
                expected_format="Evidence/Assertion/Event GraphRef",
                searched_sources=["task refs", "dependency results"],
            ))
        if portfolio_ref is None:
            missing.append(MissingContextItem(
                key="portfolio_snapshot_ref",
                description="缺少当前用户组合快照。",
                expected_format="PortfolioSnapshot GraphRef",
                searched_sources=["task refs", "dependency results"],
            ))
        if missing:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                focus_refs=task.focus_refs,
                summary="影响路径分析缺少必要图锚点。",
                missing_items=missing,
            )
        paths = self.impact_service.find_paths(
            cause_refs=causes,
            portfolio_ref=portfolio_ref,
            as_of_time=task.as_of_time,
        )
        summary = self.impact_service.summarize_paths(paths)
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED if paths else ResultStatus.PARTIAL,
            focus_refs=[*causes, portfolio_ref],
            summary=(
                f"已找到 {len(paths)} 条可追踪影响路径，涉及 {summary.get('holding_count', 0)} 个持仓。"
                if paths
                else "当前权威图和证据图中未找到新闻到持仓的可验证路径。"
            ),
            findings=[{"kind": "portfolio_impact_paths", **_safe(summary)}],
            graph_path_refs=paths,
            evidence_refs=[ref for ref in causes if ref.node_kind == GraphNodeKind.EVIDENCE],
            confidence=max((path.confidence for path in paths), default=0.0),
            warnings=[] if paths else ["no_validated_impact_path"],
            metadata={"produced_refs": [portfolio_ref.to_dict()]},
        )

    def _run_risk(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> GraphWorkerResult:
        refs = _refs_from_dependencies(dependency_results, kinds={GraphNodeKind.OBJECT})
        portfolio_ref = next((ref for ref in refs if "portfolio" in ref.node_id.lower()), None)
        raw = self.provider.analyze_risk(
            user_id=task.user_id,
            output_dir=output_dir,
            db_path=db_path,
            portfolio_ref=portfolio_ref,
        )
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED if raw.get("success") else ResultStatus.FAILED,
            focus_refs=[portfolio_ref] if portfolio_ref else task.focus_refs,
            summary=str(raw.get("message") or ("已完成组合风险分析。" if raw.get("success") else "组合风险分析失败。")),
            findings=[{"kind": "portfolio_risk", "data": _safe(raw.get("data") or {}), "record_count": len(raw.get("records") or [])}],
            confidence=0.9 if raw.get("success") else 0.0,
            warnings=[str(item) for item in raw.get("warnings") or []],
        )

    def _run_strategy_guard(
        self,
        task: GraphAgentTask,
        *,
        current_user_request: str,
        dependency_results: dict[str, dict[str, Any]],
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> GraphWorkerResult:
        from agent.tool_engine import AGENT_MAIN, OP_PROPOSAL, execute_tool_legacy_dict, get_tool_registry_v2

        registry = get_tool_registry_v2()
        catalog: list[dict[str, Any]] = []
        for definition in registry.list(agent_type=AGENT_MAIN, operation_type=OP_PROPOSAL):
            if str(getattr(definition, "operation_type", "")).lower() != str(OP_PROPOSAL).lower():
                continue
            catalog.append({
                "name": str(definition.name),
                "description": str(definition.description),
                "input_schema": dict(definition.input_schema or {}),
                "produced_outputs": list(definition.produced_outputs or []),
                "requires_approval": bool(definition.requires_approval),
            })
        if not catalog:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                focus_refs=task.focus_refs,
                summary="没有可用的 Proposal 能力，未进行任何写入。",
                warnings=["proposal_capability_catalog_empty"],
            )
        allowed = {item["name"] for item in catalog}

        def validate(payload: dict[str, Any]) -> None:
            action = str(payload.get("action") or "").lower()
            if action not in {"execute_proposal", "need_context", "blocked"}:
                raise RuntimeError("invalid_strategy_guard_action")
            if action == "execute_proposal" and str(payload.get("capability") or "") not in allowed:
                raise RuntimeError("proposal_capability_not_allowed")

        decision = self.llm_service.generate_json(
            stage="graph_strategy_guard",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 Strategy Guard 的私有 Proposal 规划器。主 Agent 看不到这些私有能力。"
                        "只能选择一个 proposal 能力生成待审批预案，禁止 Commit，禁止表示已经执行。"
                        "Agent 公共实体引用均为 GraphRef，不得要求主 Agent 提供 stock_code。"
                        "严格输出 JSON：{\"action\":\"execute_proposal|need_context|blocked\","
                        "\"capability\":\"\",\"parameters\":{},\"reason\":\"\",\"missing_items\":[]}。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "task": task.safe_for_coordinator(),
                        "user_request": current_user_request,
                        "dependency_results": _safe(_dependency_results(dependency_results)),
                        "available_proposal_capabilities": catalog,
                        "reply_language": language,
                    }, ensure_ascii=False, default=str),
                },
            ],
            max_output_tokens=2200,
            validator=validate,
            operation=task.task_type,
        )
        action = str(decision.get("action") or "").lower()
        if action == "need_context":
            missing = [
                MissingContextItem(
                    key=str(item.get("key") or "proposal_context"),
                    description=str(item.get("description") or "生成预案所需上下文"),
                    expected_format=str(item.get("expected_format") or "明确目标或数值"),
                    reason=str(decision.get("reason") or "无法安全生成 Proposal。"),
                    searched_sources=["task", "dependency_results", "private_proposal_planner"],
                )
                for item in decision.get("missing_items") or []
                if isinstance(item, dict)
            ]
            return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.NEED_CONTEXT, focus_refs=task.focus_refs, summary="生成预案前需要补充信息。", missing_items=missing)
        if action == "blocked":
            return GraphWorkerResult(task_id=task.task_id, agent_id=task.assigned_agent, status=ResultStatus.BLOCKED, focus_refs=task.focus_refs, summary=str(decision.get("reason") or "当前请求不能安全形成预案。"))

        params = dict(decision.get("parameters") or {})
        # Runtime user_id is authoritative; model-generated account_id is never trusted.
        params.pop("account_id", None)
        params["user_id"] = task.user_id
        raw = execute_tool_legacy_dict(
            str(decision.get("capability") or ""),
            params,
            context={
                **dict(execution_context or {}),
                "output_dir": output_dir,
                "db_path": db_path,
                "default_top_k": default_top_k,
                "user_id": task.user_id,
                "session_id": task.session_id,
                "conversation_id": task.session_id,
                "run_id": task.run_id,
                "task_id": task.task_id,
                "agent_role": task.assigned_agent,
                "dependency_results": dependency_results,
                "graph_refs": [ref.to_dict() for ref in task.focus_refs + task.context_refs],
                "llm_runtime_settings": self.llm_service.settings,
                "llm_profile_id": self.llm_service.profile_id,
                "llm_config_hash": self.llm_service.config_hash,
            },
            agent_type=AGENT_MAIN,
            approval_granted=False,
        )
        success = bool(raw.get("success"))
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        plan_id = str(data.get("plan_id") or raw.get("plan_id") or "")
        proposal_id = str(data.get("proposal_id") or raw.get("proposal_id") or "")
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PROPOSAL_READY if success else ResultStatus.FAILED,
            focus_refs=task.focus_refs,
            summary=str(raw.get("message") or ("已生成待审批预案。" if success else "预案生成失败。")),
            findings=[{"kind": "proposal", "plan_id": plan_id, "proposal_id": proposal_id, "data": _safe(data)}],
            confidence=1.0 if success else 0.0,
            warnings=[str(item) for item in raw.get("warnings") or []],
            metadata={"plan_id": plan_id, "proposal_id": proposal_id, "requires_approval": success},
        )

    def _run_report_writer(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        language: str,
    ) -> GraphWorkerResult:
        safe_results = [
            {
                "contract_version": str(item.get("contract_version") or "graph_worker_result.v1"),
                "task_id": str(item.get("task_id") or ""),
                "agent_id": str(item.get("agent_id") or ""),
                "status": str(item.get("status") or ""),
                "focus_refs": _safe(item.get("focus_refs") or []),
                "summary": str(item.get("summary") or "")[:2000],
                "findings": _safe(item.get("findings") or []),
                "recommendations": _safe(item.get("recommendations") or []),
                "evidence_refs": _safe(item.get("evidence_refs") or []),
                "graph_path_refs": _safe(item.get("graph_path_refs") or []),
                "warnings": _safe(item.get("warnings") or []),
                "missing_items": _safe(item.get("missing_items") or []),
                "confidence": item.get("confidence"),
            }
            for item in _dependency_results(dependency_results)
        ]
        if not safe_results:
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                focus_refs=task.focus_refs,
                summary="报告生成缺少上游 GraphWorkerResult。",
                missing_items=[MissingContextItem(key="worker_results", description="需要上游专业 Worker 的标准结果。", searched_sources=["dependency_results"])],
            )
        system = (
            "你是金融 Agent 的 Report Writer。你只能使用输入中的 GraphWorkerResult，不能重新解析原始新闻正文，"
            "不能猜证券代码，不能引用未提供的实体、证据或影响路径。明确区分已验证事实、来源声明、间接关系和不确定性。"
            "若没有影响路径，必须明确说当前证据不足，不能把新闻提及当作因果影响。"
            "不要暴露内部 Agent 名称、task_id、GraphRef 技术字段、工具名或数据库实现。"
            "使用中文回答。" if language != "en" else
            "You are the financial Agent report writer. Use only the supplied GraphWorkerResult contracts. Do not re-parse raw evidence or invent entity identities, evidence, or causal paths. Clearly separate validated facts, claims, indirect relations, and uncertainty. Do not expose internal agents, task IDs, tools, GraphRef fields, or storage details."
        )
        answer = self.llm_service.generate_text(
            stage="graph_report_writer",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"objective": task.objective, "worker_results": safe_results}, ensure_ascii=False, default=str)},
            ],
            max_output_tokens=3000,
            operation="write_graph_grounded_report",
        )
        statuses = {str(item.get("status") or "") for item in safe_results}
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PARTIAL if statuses & {"partial", "need_context", "failed"} else ResultStatus.COMPLETED,
            focus_refs=task.focus_refs,
            summary=str(answer or ""),
            findings=[{"kind": "report", "text": str(answer or "")}],
            confidence=min([float(item.get("confidence") or 0.0) for item in safe_results] or [0.0]),
            evidence_refs=_refs_from_dependencies(dependency_results, kinds={GraphNodeKind.EVIDENCE}),
            graph_path_refs=[
                GraphPathRef(**path)
                for item in safe_results
                for path in item.get("graph_path_refs") or []
                if isinstance(path, dict)
            ],
        )

    def _run_diagnostic(self, task: GraphAgentTask) -> GraphWorkerResult:
        self.provider.identity.store.verify_connectivity()
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            focus_refs=task.focus_refs,
            summary="Neo4j 金融事实图连接正常。",
            findings=[{"kind": "neo4j_connectivity", "status": "ok", "graph_id": self.provider.identity.store.graph_id}],
            confidence=1.0,
        )

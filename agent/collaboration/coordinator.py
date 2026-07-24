from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from
from agent.graph.errors import GraphConfigurationError, GraphUnavailableError
from agent.graph.identity import GraphEntityIdentityService
from agent.graph.settings import Neo4jSettings
from agent.graph.store import Neo4jFinancialGraphStore
from agent.graph.patch_validator import GraphPatchValidator
from agent.graph.evidence_ingestion import EvidenceIngestionService
from agent.graph.portfolio_graph import PortfolioGraphService
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.graph.impact_service import GraphImpactService

from .agent_directory import AgentDirectory, REPORT_WRITER
from .control_gateway import ControlGateway
from .entry_decision import MainEntryDecisionPlanner, RequestMode
from .models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .planner import CoordinatorPlanner
from .session_memory import SessionMemoryStore
from .specialist_runtime import SpecialistRuntime


def _dedupe_refs(refs: list[GraphRef]) -> list[GraphRef]:
    result: list[GraphRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.node_id, ref.role)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _walk_graph_refs(value: Any, *, depth: int = 0) -> list[GraphRef]:
    if depth > 8:
        return []
    refs: list[GraphRef] = []
    if isinstance(value, GraphRef):
        return [value]
    if isinstance(value, dict):
        if value.get("node_id") and value.get("node_kind"):
            try:
                refs.append(GraphRef.from_dict(value))
            except Exception:
                pass
        for key, item in value.items():
            if str(key).lower() in {"api_key", "password", "secret", "confirmation_token", "raw_payload"}:
                continue
            refs.extend(_walk_graph_refs(item, depth=depth + 1))
    elif isinstance(value, (list, tuple)):
        for item in list(value)[:200]:
            refs.extend(_walk_graph_refs(item, depth=depth + 1))
    return _dedupe_refs(refs)


def _clarification_question(items: list[MissingContextItem], language: str) -> str:
    descriptions = [item.description for item in items if item.description]
    if language == "en":
        return "Please provide or select: " + "; ".join(descriptions[:4])
    return "请补充或选择：" + "；".join(descriptions[:4])


class AgentCollaborationCoordinator:
    """Existing Main-Agent pattern with a Neo4j/GraphRef-only data boundary."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        db_path: str | Path | None,
        llm_service: LLMService,
        graph_settings: Neo4jSettings | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.db_path = db_path
        self.llm_service = llm_service
        self.memory = SessionMemoryStore(output_dir=output_dir)
        self.directory = AgentDirectory()
        settings = graph_settings or Neo4jSettings.from_env()
        self.store = Neo4jFinancialGraphStore(settings)
        self.store.verify_connectivity()
        self.store.ensure_schema()
        self.identity = GraphEntityIdentityService(self.store)
        validator = GraphPatchValidator(self.store)
        provider = GraphProviderAdapter(
            identity=self.identity,
            evidence_ingestion=EvidenceIngestionService(validator),
            portfolio_graph=PortfolioGraphService(self.identity, validator),
        )
        self.specialist = SpecialistRuntime(
            llm_service=llm_service,
            provider=provider,
            impact_service=GraphImpactService(self.store),
        )
        self.entry = MainEntryDecisionPlanner(llm_service=llm_service)
        self.planner = CoordinatorPlanner(self.directory, llm_service=llm_service)

    def close(self) -> None:
        self.store.close()

    def _memory_refs(self, session_id: str) -> list[GraphRef]:
        item = self.memory.get(session_id, "active_graph_refs")
        return refs_from(item.value if item is not None else [])

    def _extract_mentions(self, query: str, language: str) -> list[dict[str, Any]]:
        hard = self.identity.extract_candidate_mentions(query)

        def validate(payload: dict[str, Any]) -> None:
            mentions = payload.get("mentions")
            if not isinstance(mentions, list):
                raise RuntimeError("entity_mentions_not_list")
            if len(mentions) > 20:
                raise RuntimeError("too_many_entity_mentions")
            for item in mentions:
                if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                    raise RuntimeError("invalid_entity_mention")
                if str(item.get("role") or "focus") not in {
                    "focus", "comparison", "cause", "impact_target", "context", "event"
                }:
                    raise RuntimeError("invalid_entity_role")

        payload = self.llm_service.generate_json(
            stage="graph_entity_candidate_extraction",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "只从用户当前请求中提取用户明确指向的现实对象、新闻/公告/研报、事件或组合目标候选。"
                        "不要从常识补充对象，不要生成代码，不要决定最终实体 ID。"
                        "当前请求中未明确出现对象时返回空数组。"
                        "角色只能是 focus、comparison、cause、impact_target、context、event。"
                        "严格输出 JSON：{\"mentions\":[{\"text\":\"\",\"role\":\"focus\"}]}。"
                    ),
                },
                {"role": "user", "content": json.dumps({"request": query, "language": language}, ensure_ascii=False)},
            ],
            max_output_tokens=900,
            validator=validate,
            operation="extract_graph_entity_candidates",
        )
        result = [dict(item) for item in payload.get("mentions") or [] if isinstance(item, dict)]
        for text in hard:
            if not any(str(item.get("text") or "") == text for item in result):
                result.append({"text": text, "role": "focus"})
        return result[:20]

    def _resolve_request_refs(
        self,
        *,
        query: str,
        inherited_refs: list[GraphRef],
        context_refs: list[GraphRef],
        as_of_time: str,
        language: str,
    ) -> tuple[list[GraphRef], list[MissingContextItem], dict[str, Any]]:
        mentions = self._extract_mentions(query, language)
        explicit_resolved: list[GraphRef] = []
        missing: list[MissingContextItem] = []
        audit: list[dict[str, Any]] = []
        for mention in mentions:
            text = str(mention.get("text") or "").strip()
            role = str(mention.get("role") or "focus")
            resolution = self.identity.resolve_request(
                query,
                inherited_refs=[],
                role=role,
                as_of_time=as_of_time,
                explicit_mentions=[text],
            )
            audit.append({"mention": text, "role": role, "resolution": resolution.to_dict()})
            if resolution.ambiguous_mentions:
                missing.append(MissingContextItem(
                    key="ambiguous_graph_entity",
                    description=f"“{text}”对应多个金融对象，需要选择具体对象。",
                    expected_format="从候选对象中选择一个",
                    reason="不能由 LLM 自行决定权威实体。",
                    searched_sources=["Neo4j identity", "Neo4j aliases", "Neo4j fulltext candidates"],
                ))
            elif resolution.unresolved_mentions:
                missing.append(MissingContextItem(
                    key="unresolved_graph_entity",
                    description=f"无法在权威金融图中确认“{text}”。",
                    expected_format="明确名称、交易所代码或已导入的 GraphRef",
                    reason="权威实体不存在或证券主数据尚未导入。",
                    searched_sources=["Neo4j identity", "Neo4j aliases"],
                ))
            else:
                explicit_resolved.extend(resolution.refs)

        # Current explicit user mentions override inherited focus. Context-provided
        # evidence/snapshot refs remain available but do not replace locked focus.
        if explicit_resolved:
            focus = explicit_resolved
        elif context_refs:
            focus = [ref for ref in context_refs if ref.role in {"focus", "cause", "impact_target", "comparison", "event"}]
            focus = focus or context_refs
        else:
            focus = inherited_refs
        return _dedupe_refs(focus), missing, {"mentions": mentions, "items": audit}

    def execute(
        self,
        *,
        query: str,
        decomposition: dict[str, Any],
        user_id: str,
        default_top_k: int,
        session_id: str,
        run_id: str,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        del decomposition
        context = dict(execution_context or {})
        memory_summary = self.memory.build_summary(session_id, limit=40)
        decision = self.entry.decide(
            query=query,
            memory_summary=memory_summary,
            execution_context=context,
            language=language,
        )
        if decision.mode in {RequestMode.CONFIRM, RequestMode.REJECT, RequestMode.LANGUAGE}:
            return ControlGateway(output_dir=self.output_dir, db_path=self.db_path).execute(
                decision=decision,
                query=query,
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                language=language,
                execution_context=context,
            )
        if decision.mode == RequestMode.UNSUPPORTED:
            answer = "当前请求超出系统能力范围。" if language != "en" else "This request is outside the system's supported scope."
            return self._empty_result(answer=answer, success=False, status="failed", warnings=[decision.reason])

        context_refs = _walk_graph_refs(context)
        inherited_refs = self._memory_refs(session_id)
        explicit_as_of = str(context.get("as_of_time") or context.get("as_of_date") or "")
        focus_refs, resolution_missing, resolution_audit = self._resolve_request_refs(
            query=query,
            inherited_refs=inherited_refs,
            context_refs=context_refs,
            as_of_time=explicit_as_of,
            language=language,
        )
        if resolution_missing:
            question = _clarification_question(resolution_missing, language)
            return {
                **self._empty_result(answer=question, success=False, status="waiting_context"),
                "need_clarification": True,
                "clarification_question": question,
                "missing_context": [item.to_dict() for item in resolution_missing],
                "graph_runtime": {
                    "contract_version": "financial_graph_runtime.v1",
                    "graph_id": self.store.graph_id,
                    "resolution_audit": resolution_audit,
                },
            }
        self.memory.put(
            session_id=session_id,
            key=f"turn:{run_id}:user_message",
            value={"user_id": user_id, "message": str(query or "")},
            value_type="conversation_turn",
            summary=str(query or "")[:500],
            source_type="user_message",
            source_ref=run_id,
            confirmed=True,
            confidence=1.0,
        )
        if focus_refs:
            self.memory.put(
                session_id=session_id,
                key="active_graph_refs",
                value=[ref.to_dict() for ref in focus_refs],
                value_type="graph_ref_list",
                summary="当前对话已确认的金融图对象引用。",
                source_type="graph_entity_resolution",
                source_ref=run_id,
                confirmed=True,
                confidence=1.0,
            )

        tasks, plan_meta = self.planner.plan(
            query=query,
            request_mode=decision.mode.value,
            session_id=session_id,
            run_id=run_id,
            user_id=user_id,
            focus_refs=focus_refs,
            context_refs=context_refs,
            memory_summary=memory_summary,
            language=language,
            as_of_time=explicit_as_of,
        )
        results, batches, timeline = self._run_dag(
            tasks,
            query=query,
            output_dir=self.output_dir,
            db_path=self.db_path,
            default_top_k=default_top_k,
            language=language,
            execution_context=context,
        )
        for result in results.values():
            for update in result.memory_updates:
                self.memory.put(
                    session_id=session_id,
                    key=update.key,
                    value=update.value,
                    value_type=update.value_type,
                    summary=update.summary,
                    source_type=update.source_type,
                    source_ref=update.source_ref or result.task_id,
                    confirmed=update.confirmed,
                    confidence=update.confidence,
                )

        public_results = {task_id: result.safe_for_coordinator() for task_id, result in results.items()}
        report = next((result for result in results.values() if result.agent_id == REPORT_WRITER), None)
        answer = report.summary if report and report.summary else self._fallback_answer(results, language)
        statuses = [result.status for result in results.values()]
        need_context = [item for result in results.values() for item in result.missing_items if item.blocking]
        failed = sum(status in {ResultStatus.FAILED, ResultStatus.BLOCKED, ResultStatus.NOT_EXECUTED} for status in statuses)
        completed = sum(status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL, ResultStatus.PROPOSAL_READY} for status in statuses)
        execution_status = (
            "waiting_context" if need_context else
            "completed" if failed == 0 else
            "partially_completed" if completed else
            "failed"
        )
        success = completed > 0 and failed == 0 and not need_context
        question = _clarification_question(need_context, language) if need_context else ""
        internal_count = len([item for item in timeline if item.get("status") not in {"not_executed"}])
        return {
            "success": success,
            "answer": answer if not question else question,
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
            "execution_order": [item.task_id for item in tasks if item.task_id in results],
            "execution_batches": batches,
            "warnings": [warning for result in results.values() for warning in result.warnings],
            "errors": [],
            "execution_status": execution_status,
            "need_clarification": bool(need_context),
            "clarification_question": question,
            "missing_context": [item.to_dict() for item in need_context],
            "observations": timeline,
            "replan_audit": [],
            "replan_count": 0,
            "invalid_replan_block_count": 0,
            "replan_limits": {"max_rounds": 2, "delegation_preserved": True},
            "agent_outputs": public_results,
            "agent_timeline": timeline,
            "handoff": {
                "handoff_available": bool(public_results),
                "handoff_count": len(public_results),
                "handoff_refs": [f"worker_result:{task_id}" for task_id in public_results],
                "safety": {"worker_private_tools": True, "coordinator_tool_visibility": "none"},
            },
            "graph_runtime": {
                "contract_version": "financial_graph_runtime.v1",
                "graph_id": self.store.graph_id,
                "task_contract": "graph_agent_task.v1",
                "result_contract": "graph_worker_result.v1",
                "focus_refs": [ref.to_dict() for ref in focus_refs],
                "resolution_audit": resolution_audit,
                "planner": plan_meta,
                "legacy_public_protocol_enabled": False,
            },
        }

    def _run_dag(
        self,
        tasks: list[GraphAgentTask],
        *,
        query: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any],
    ) -> tuple[dict[str, GraphWorkerResult], list[dict[str, Any]], list[dict[str, Any]]]:
        results: dict[str, GraphWorkerResult] = {}
        pending = {task.task_id: task for task in tasks}
        batches: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        batch_index = 0
        while pending:
            ready = [task for task in pending.values() if all(dep in results for dep in task.dependency_task_ids)]
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
            batch_index += 1
            batches.append({
                "batch_index": batch_index,
                "task_ids": [task.task_id for task in ready],
                "agents": [task.assigned_agent for task in ready],
                "parallel": len(ready) > 1,
            })
            max_workers = min(4, len(ready))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        self.specialist.run,
                        task,
                        current_user_request=query,
                        dependency_results={dep: results[dep].safe_for_coordinator() for dep in task.dependency_task_ids if dep in results},
                        output_dir=output_dir,
                        db_path=db_path,
                        default_top_k=default_top_k,
                        language=language,
                        execution_context=execution_context,
                    ): task
                    for task in ready
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
                    timeline.append({
                        "task_id": task.task_id,
                        "agent_id": task.assigned_agent,
                        "status": result.status.value,
                        "summary": result.summary[:500],
                    })
                    pending.pop(task.task_id, None)
        return results, batches, timeline

    @staticmethod
    def _fallback_answer(results: dict[str, GraphWorkerResult], language: str) -> str:
        summaries = [result.summary for result in results.values() if result.summary]
        if summaries:
            return "\n\n".join(summaries)
        return "目前不能回答，相关数据链路尚未返回结果。" if language != "en" else "The system cannot answer because the required data path returned no result."

    @staticmethod
    def _empty_result(*, answer: str, success: bool, status: str, warnings: list[str] | None = None) -> dict[str, Any]:
        return {
            "success": success,
            "answer": answer,
            "task_results": {},
            "graph_worker_results": {"contract_version": "graph_worker_results.v1", "items": [], "task_count": 0, "completed_count": 0, "failed_count": 0, "waiting_context_count": 0},
            "tool_calls": [],
            "internal_tool_call_count": 0,
            "execution_order": [],
            "execution_batches": [],
            "warnings": list(warnings or []),
            "errors": [],
            "execution_status": status,
            "need_clarification": False,
            "clarification_question": "",
            "missing_context": [],
            "observations": [],
            "replan_audit": [],
            "replan_count": 0,
            "invalid_replan_block_count": 0,
            "replan_limits": {"max_rounds": 0},
            "agent_outputs": {},
            "agent_timeline": [],
            "handoff": {"handoff_available": False, "handoff_count": 0, "handoff_refs": []},
        }

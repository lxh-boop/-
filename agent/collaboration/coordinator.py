from __future__ import annotations

import json
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
from agent.worker_tools import (
    build_worker_tool_directory,
    build_worker_tool_registry,
)
from agent.worker_tools.application_backends import (
    ApplicationMarketToolBackend,
)

from .agent_directory import AgentDirectory
from .context_handoff import MainContextHandoff
from .context_resume import (
    ContextResumeRuntime,
    confirmed_memory_values,
    context_requests,
    descendant_task_ids,
    resume_context_snapshot,
)
from .control_gateway import ControlGateway
from .dag_runtime import run_worker_dag
from .entry_decision import MainEntryDecisionPlanner, RequestMode
from .models import (
    GraphAgentTask,
    GraphWorkerResult,
    MissingContextItem,
    ResultStatus,
    TaskStatus,
    WorkerContextRequest,
)
from .planner import CoordinatorPlanner
from .result_assembler import assemble_main_result
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
        self.context_handoff = MainContextHandoff(
            memory=self.memory,
            llm_service=llm_service,
        )
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
        worker_tool_registry = build_worker_tool_registry(
            evidence_backend=provider,
            portfolio_backend=provider,
            market_backend=ApplicationMarketToolBackend(
                stock_ref_resolver=provider.provider_symbol,
            ),
            risk_backend=provider,
            diagnostic_backend=provider,
            impact_backend=GraphImpactService(self.store),
        )
        self.specialist = SpecialistRuntime(
            llm_service=llm_service,
            worker_tool_directory=build_worker_tool_directory(
                worker_tool_registry
            ),
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
        resumed = self._resume_waiting_context(
            query=query,
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            language=language,
            default_top_k=default_top_k,
            execution_context=context,
            memory_summary=memory_summary,
        )
        if resumed is not None:
            return resumed
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
        return self._execute_plan(
            tasks=tasks,
            query=query,
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            default_top_k=default_top_k,
            language=language,
            execution_context=context,
            focus_refs=focus_refs,
            resolution_audit=resolution_audit,
            plan_meta=plan_meta,
        )

    def _resume_waiting_context(
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
        return ContextResumeRuntime(
            memory=self.memory,
            handoff=self.context_handoff,
            execute_plan=self._execute_plan,
            empty_result=self._empty_result,
        ).try_resume(
            query=query,
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            language=language,
            default_top_k=default_top_k,
            execution_context=execution_context,
            memory_summary=memory_summary,
        )

    def _execute_plan(
        self,
        *,
        tasks: list[GraphAgentTask],
        query: str,
        user_id: str,
        session_id: str,
        run_id: str,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any],
        focus_refs: list[GraphRef],
        resolution_audit: dict[str, Any],
        plan_meta: dict[str, Any],
        initial_results: dict[str, GraphWorkerResult] | None = None,
    ) -> dict[str, Any]:
        context = {
            **execution_context,
            "session_memory_values": {
                **confirmed_memory_values(self.memory, session_id),
                **dict(
                    execution_context.get("session_memory_values")
                    or {}
                ),
            },
        }
        results, batches, timeline = run_worker_dag(
            tasks,
            specialist=self.specialist,
            query=query,
            output_dir=self.output_dir,
            db_path=self.db_path,
            default_top_k=default_top_k,
            language=language,
            execution_context=context,
            initial_results=initial_results,
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

        pending_context_requests = context_requests(results)
        memory_values, unresolved_items = (
            self.context_handoff.memory_values(
                session_id,
                pending_context_requests,
            )
            if pending_context_requests
            else ({}, [])
        )
        if (
            pending_context_requests
            and not unresolved_items
            and memory_values
            and not context.get("context_auto_resume_attempted")
        ):
            root_ids = {
                request.source_task_id
                for request in pending_context_requests
            }
            rerun_ids = descendant_task_ids(tasks, root_ids)
            retained = {
                task_id: result
                for task_id, result in results.items()
                if task_id not in rerun_ids
                and result.status
                in {
                    ResultStatus.COMPLETED,
                    ResultStatus.PARTIAL,
                    ResultStatus.PROPOSAL_READY,
                }
            }
            for task in tasks:
                if task.task_id in rerun_ids:
                    task.attempt += 1
                    task.status = TaskStatus.CREATED
            return self._execute_plan(
                tasks=tasks,
                query=query,
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                default_top_k=default_top_k,
                language=language,
                execution_context={
                    **context,
                    "context_auto_resume_attempted": True,
                    "resolved_context": {
                        **dict(context.get("resolved_context") or {}),
                        **memory_values,
                    },
                },
                focus_refs=focus_refs,
                resolution_audit=resolution_audit,
                plan_meta=plan_meta,
                initial_results=retained,
            )

        if pending_context_requests and unresolved_items:
            request_id = pending_context_requests[0].request_id
            source_task_id = pending_context_requests[0].source_task_id
            task_by_id = {task.task_id: task for task in tasks}
            anchor_source = task_by_id.get(source_task_id) or tasks[0]
            anchor = GraphAgentTask.from_dict(anchor_source.to_dict())
            anchor.metadata["resume_state"] = {
                "query": query,
                "default_top_k": default_top_k,
                "language": language,
                "tasks": [task.to_dict() for task in tasks],
                "results": {
                    task_id: result.to_dict()
                    for task_id, result in results.items()
                },
                "context_requests": [
                    request.to_dict()
                    for request in pending_context_requests
                ],
                "focus_refs": [
                    ref.to_dict() for ref in focus_refs
                ],
                "resolution_audit": resolution_audit,
                "plan_meta": plan_meta,
                "execution_context": resume_context_snapshot(
                    context
                ),
                "resolved_context": memory_values,
            }
            self.memory.register_waiting_task(
                anchor,
                [item.key for item in unresolved_items],
            )
            question = self.context_handoff.clarification_question(
                unresolved_items,
                language=language,
            )
        else:
            request_id = ""
            question = ""

        return assemble_main_result(
            tasks=tasks,
            results=results,
            batches=batches,
            timeline=timeline,
            directory=self.directory,
            language=language,
            question=question,
            request_id=request_id,
            graph_id=self.store.graph_id,
            focus_refs=focus_refs,
            resolution_audit=resolution_audit,
            plan_meta=plan_meta,
        )

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

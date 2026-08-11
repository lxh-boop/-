from __future__ import annotations

import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import compact_json_dumps

from agent.console_trace import flow_event, trace_exception
from agent.context.context_hydrator import ContextHydrator, ContextRequirement
from agent.context.context_sufficiency_gate import ContextAndEntitySufficiencyGate
from agent.runtime_state import RunCheckpoint, RunCheckpointStore, RunSlotStore

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

from .completion import flow_decision, non_success_completion_report, validate_completion_report
from .worker_directory import CapabilityWorkerDirectory, REPORT_WRITER
from .control_gateway import ControlGateway
from .entry_decision import MainEntryDecisionPlanner, RequestMode
from .models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .planner import CoordinatorPlanner
from .runtime_services import CollaborationRuntimeServices
from .session_state import SessionStateStore
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


def _authoritative_entity_catalog(
    resolution_audit: dict[str, Any],
    focus_refs: list[GraphRef],
) -> list[dict[str, Any]]:
    """Preserve labels confirmed by GraphRef resolution for downstream reporting."""

    selected_ids = {ref.node_id for ref in focus_refs}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list((resolution_audit or {}).get("items") or []):
        if not isinstance(item, dict):
            continue
        resolution = item.get("resolution") if isinstance(item.get("resolution"), dict) else {}
        for candidate in list(resolution.get("candidates") or []):
            if not isinstance(candidate, dict):
                continue
            graph_ref = candidate.get("graph_ref") if isinstance(candidate.get("graph_ref"), dict) else {}
            node_id = str(graph_ref.get("node_id") or "")
            if not node_id or node_id not in selected_ids or node_id in seen:
                continue
            display_label = str(candidate.get("display_name") or "").strip()
            public_code = node_id.rsplit(":", 1)[-1]
            if not (len(public_code) == 6 and public_code.isdigit()):
                public_code = ""
            rows.append(
                {
                    "entity_ref": dict(graph_ref),
                    "node_id": node_id,
                    "public_code": public_code,
                    "display_label": display_label,
                    "identity_source": str(candidate.get("matched_by") or graph_ref.get("source") or ""),
                    "identity_locked": bool(graph_ref.get("locked")),
                }
            )
            seen.add(node_id)
    return rows


def _bind_authoritative_task_context(
    tasks: list[GraphAgentTask],
    *,
    entity_catalog: list[dict[str, Any]],
) -> None:
    for task in tasks:
        task.metadata["authoritative_entity_catalog"] = [dict(item) for item in entity_catalog]


def _bind_task_completion_contracts(
    tasks: list[GraphAgentTask],
    *,
    directory: CapabilityWorkerDirectory,
) -> None:
    # Capability contracts are already carried by each task.  Runtime no longer
    # compiles a task-type completion contract.
    del tasks, directory


def _planning_memory_summary(
    *,
    session_summary: str,
    long_term_memory_summary: str,
    inherit_previous_focus: bool,
) -> str:
    """Build the memory view that may influence business-intent planning.

    MainEntryDecision owns whether the current request inherits the previous
    conversation focus.  When it explicitly rejects that inheritance, the
    canonical-intent planner must not be allowed to re-introduce a previous
    named financial entity through ``session_summary``.  Long-term memory stays
    available for non-focus user preferences/constraints; authoritative entity
    identity still comes exclusively from GraphRef resolution.
    """

    items: list[str] = []
    if inherit_previous_focus and str(session_summary or "").strip():
        items.append(str(session_summary).strip())
    if str(long_term_memory_summary or "").strip():
        items.append(str(long_term_memory_summary).strip())
    return "\n".join(items)[:4800]


def _has_forward_replan_context_blocker(observations: list[dict[str, Any]]) -> bool:
    """Return True when a failure belongs to the context/authority layer.

    Worker forward-replan may replace failed business Workers, but it must not
    manufacture user input or authoritative GraphRefs that only the context and
    identity layers are allowed to establish.
    """

    return any(
        str(item.get("failure_kind") or "") in {
            "user_input_required",
            "worker_context_unresolved",
        }
        for item in observations
    )



class AgentCollaborationCoordinator:
    """Existing Main-Agent pattern with a Neo4j/GraphRef-only data boundary."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        db_path: str | Path | None,
        llm_service: LLMService,
        graph_settings: Neo4jSettings | None = None,
        runtime_services: CollaborationRuntimeServices | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.db_path = db_path
        self.llm_service = llm_service
        self.runtime_services = runtime_services
        self.session_state = SessionStateStore(output_dir=output_dir)
        self.checkpoints = RunCheckpointStore(output_dir)
        self.slot_store = RunSlotStore(output_dir)
        self.context_hydrator = ContextHydrator(
            session_state=self.session_state,
            checkpoint_store=self.checkpoints,
            output_dir=str(output_dir),
        )
        self.sufficiency_gate = ContextAndEntitySufficiencyGate()
        self.directory = CapabilityWorkerDirectory()
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
            slot_store=self.slot_store,
            directory=self.directory,
        )
        self.entry = MainEntryDecisionPlanner(llm_service=llm_service)
        self.planner = CoordinatorPlanner(
            self.directory,
            llm_service=llm_service,
            worker_tool_directory=self.specialist.worker_tool_directory,
        )

    def close(self) -> None:
        self.store.close()

    def _memory_refs(self, session_id: str) -> list[GraphRef]:
        item = self.session_state.get(session_id, "active_graph_refs")
        return refs_from(item.value if item is not None else [])

    def _extract_mentions(
        self,
        query: str,
        language: str,
        context_binding: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        lexical_candidates = self.identity.extract_candidate_mentions(query)

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
                        "只从用户当前请求中提取用户明确指向、且需要进入金融图解析的现实金融对象、新闻/公告/研报或事件。"
                        "context_binding 是 MainAgent 对当前业务范围的语义判断；portfolio、account、global、none 是业务范围，"
                        "不能把‘我的持仓’、‘当前账户’等范围词误当成单只证券实体。只有请求中明确出现具体证券、公司、行业、事件或已命名组合对象时才输出 mention。"
                        "lexical_candidates 只是字符串候选，不是权威结论；你必须根据用户目标决定是否保留。"
                        "不要从常识补充对象，不要生成代码，不要决定最终实体 ID。当前请求中没有需要 GraphRef 解析的明确对象时返回空数组。"
                        "角色只能是 focus、comparison、cause、impact_target、context、event。"
                        "严格输出 JSON：{\"mentions\":[{\"text\":\"\",\"role\":\"focus\"}]}。"
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps({
                        "request": query,
                        "language": language,
                        "context_binding": dict(context_binding or {}),
                        "lexical_candidates": list(lexical_candidates or []),
                    }),
                },
            ],
            max_output_tokens=500,
            validator=validate,
            operation="extract_graph_entity_candidates",
            disable_thinking=True,
        )
        return [
            dict(item)
            for item in payload.get("mentions") or []
            if isinstance(item, dict)
        ][:20]

    def _resolve_request_refs(
        self,
        *,
        query: str,
        inherited_refs: list[GraphRef],
        context_refs: list[GraphRef],
        as_of_time: str,
        language: str,
        context_binding: dict[str, Any] | None = None,
    ) -> tuple[list[GraphRef], list[MissingContextItem], dict[str, Any]]:
        extractor = self._extract_mentions
        try:
            parameter_count = len(inspect.signature(extractor).parameters)
        except (TypeError, ValueError):
            parameter_count = 3
        mentions = (
            extractor(query, language, context_binding)
            if parameter_count >= 3
            else extractor(query, language)
        )
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

        # Current explicit user mentions always win. Whether previous focus is
        # inherited is a structured MainAgent semantic decision, not a keyword
        # rule. Account, portfolio, global and entity-free requests therefore do
        # not accidentally retain a prior single-security focus.
        binding = dict(context_binding or {})
        inherit_previous = bool(binding.get("inherit_previous_focus"))
        if explicit_resolved:
            focus = explicit_resolved
        elif context_refs:
            focus = [
                ref for ref in context_refs
                if ref.role in {"focus", "cause", "impact_target", "comparison", "event"}
            ]
            focus = focus or context_refs
        elif inherit_previous:
            focus = inherited_refs
        else:
            focus = []
        return _dedupe_refs(focus), missing, {
            "mentions": mentions,
            "items": audit,
            "context_binding": binding,
        }

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
        if self.runtime_services is not None:
            self.runtime_services.validate_identity(
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
            )
        context = dict(execution_context or {})
        memory_summary = self.session_state.build_summary(session_id, limit=40)
        flow_event(
            "MAIN_ENTRY_DECISION_STARTED",
            {
                "request": query,
                "memory_summary_chars": len(memory_summary),
                "execution_context_keys": sorted(context.keys()),
            },
            run_id=run_id,
        )
        decision = self.entry.decide(
            query=query,
            memory_summary=memory_summary,
            execution_context=context,
            language=language,
        )
        flow_event(
            "MAIN_ENTRY_DECISION_COMPLETED",
            {
                "request_mode": decision.mode.value,
                "routing_reason": decision.reason,
                "source": decision.source,
                "confidence": decision.confidence,
                "context_binding": decision.context_binding.to_dict(),
                "semantic_authority": "routing_only",
                "business_intent_owner": "canonical_intent_contract",
            },
            run_id=run_id,
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

        requirements = [
            ContextRequirement(
                slot_id="session_summary",
                required=False,
                source_preferences=["session_state"],
            ),
            ContextRequirement(
                slot_id="long_term_memory",
                required=False,
                source_preferences=["sqlite_memory_store"],
            ),
            ContextRequirement(
                slot_id="pending_runs",
                required=False,
                source_preferences=["run_checkpoint"],
            ),
        ]
        if decision.context_binding.inherit_previous_focus:
            requirements.append(ContextRequirement(
                slot_id="previous_focus_entities",
                required=True,
                source_preferences=["session_state", "run_checkpoint"],
                allow_session_inheritance=True,
            ))
        hydrated = self.context_hydrator.hydrate(
            user_id=user_id,
            session_id=session_id,
            requirements=requirements,
            query=query,
            run_id=run_id,
            execution_context=context,
        )
        context.setdefault("available_parameters", dict(hydrated.available_parameters))
        context.setdefault("permission_context", dict(hydrated.permission_context))
        planning_memory_summary = _planning_memory_summary(
            session_summary=hydrated.session_summary,
            long_term_memory_summary=hydrated.long_term_memory_summary,
            inherit_previous_focus=decision.context_binding.inherit_previous_focus,
        )
        # Keep the full conversation summary in runtime context for audit and
        # non-business conversational handling.  The MainAgent business planner
        # receives the authority-filtered view below.
        context["memory_summary"] = memory_summary
        context["long_term_memory_refs"] = list(hydrated.long_term_memory_refs)
        flow_event(
            "CONTEXT_HYDRATED",
            {
                "source_audit": hydrated.source_audit,
                "previous_focus_ref_count": len(hydrated.previous_focus_refs),
                "pending_run_ids": hydrated.pending_run_ids,
                "available_parameter_keys": sorted(hydrated.available_parameters),
                "long_term_memory_ref_count": len(hydrated.long_term_memory_refs),
            },
            run_id=run_id,
        )
        context_refs = _walk_graph_refs(context)
        inherited_refs = hydrated.previous_focus_refs
        explicit_as_of = str(context.get("as_of_time") or context.get("as_of_date") or "")
        flow_event(
            "GRAPH_REF_RESOLUTION_STARTED",
            {
                "context_ref_count": len(context_refs),
                "inherited_ref_count": len(inherited_refs),
                "as_of_time": explicit_as_of,
                "context_binding": decision.context_binding.to_dict(),
            },
            run_id=run_id,
        )
        focus_refs, resolution_missing, resolution_audit = self._resolve_request_refs(
            query=query,
            inherited_refs=inherited_refs,
            context_refs=context_refs,
            as_of_time=explicit_as_of,
            language=language,
            context_binding=decision.context_binding.to_dict(),
        )
        flow_event(
            "GRAPH_REF_RESOLUTION_COMPLETED",
            {
                "focus_ref_count": len(focus_refs),
                "focus_refs": [ref.to_dict() for ref in focus_refs],
                "missing_context": [item.to_dict() for item in resolution_missing],
                "resolution_audit": resolution_audit,
            },
            run_id=run_id,
            level="WARNING" if resolution_missing else "INFO",
        )
        if resolution_missing:
            sufficiency = self.sufficiency_gate.evaluate(
                missing_items=resolution_missing,
                available_parameters=hydrated.available_parameters,
            )
            self.checkpoints.save(RunCheckpoint(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                status=(
                    "waiting_user_input"
                    if sufficiency.missing_parameters or sufficiency.unresolved_entities
                    else "waiting_context"
                ),
                current_node_id="entity_resolution",
                blocked_task_id="",
                resolved_entity_refs=[ref.to_dict() for ref in focus_refs],
                missing_parameters=list(sufficiency.missing_parameters),
                missing_context_slots=[*sufficiency.missing_context_slots, *sufficiency.unresolved_entities],
            ))
            flow_event("CONTEXT_SUFFICIENCY_BLOCKED", sufficiency.to_dict(), run_id=run_id, level="WARNING")
            question = _clarification_question(resolution_missing, language)
            return {
                **self._empty_result(answer=question, success=False, status="waiting_context"),
                "need_clarification": True,
                "clarification_question": question,
                "missing_context": [item.to_dict() for item in resolution_missing],
                "graph_runtime": {
                    "contract_version": "capability_contract_runtime.v1",
                    "graph_id": self.store.graph_id,
                    "resolution_audit": resolution_audit,
                },
            }
        self.session_state.put(
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
            self.session_state.put(
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

        self.checkpoints.save(RunCheckpoint(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            status="running",
            current_node_id="capability_planning",
            resolved_entity_refs=[ref.to_dict() for ref in focus_refs],
        ))
        flow_event(
            "WORKER_PLANNING_STARTED",
            {
                "request_mode": decision.mode.value,
                "focus_ref_count": len(focus_refs),
                "context_ref_count": len(context_refs),
                "worker_selection_owner": "main_agent",
                "planning_mode": "intent_then_descriptions_then_worker_calls_then_worker_dag",
                "worker_loading": "all_public_descriptions_upfront",
                "runtime_assignment_role": "validate_only",
                "raw_request_semantic_owner": "canonical_intent_contract",
                "planning_memory_policy": {
                    "previous_focus_inheritance": bool(decision.context_binding.inherit_previous_focus),
                    "session_summary_included": bool(
                        decision.context_binding.inherit_previous_focus
                        and str(hydrated.session_summary or "").strip()
                    ),
                    "long_term_memory_included": bool(str(hydrated.long_term_memory_summary or "").strip()),
                },
            },
            run_id=run_id,
        )
        try:
            tasks, plan_meta = self.planner.plan(
                query=query,
                request_mode=decision.mode.value,
                session_id=session_id,
                run_id=run_id,
                user_id=user_id,
                focus_refs=focus_refs,
                context_refs=context_refs,
                memory_summary=planning_memory_summary,
                language=language,
                as_of_time=explicit_as_of,
                context_binding=decision.context_binding.to_dict(),
            )
        except Exception as exc:
            flow_event(
                "WORKER_PLANNING_FAILED",
                {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "diagnostics": getattr(exc, "diagnostics", {}),
                },
                run_id=run_id,
                level="ERROR",
            )
            trace_exception(
                "coordinator.worker_planning.failed",
                exc,
                run_id=run_id,
            )
            raise
        entity_catalog = _authoritative_entity_catalog(resolution_audit, focus_refs)
        _bind_authoritative_task_context(tasks, entity_catalog=entity_catalog)
        _bind_task_completion_contracts(tasks, directory=self.directory)
        flow_event(
            "WORKER_PLANNING_COMPLETED",
            {
                "task_count": len(tasks),
                "planner": plan_meta,
                "tasks": [task.safe_for_coordinator() for task in tasks],
            },
            run_id=run_id,
        )
        if self.runtime_services is not None:
            self.runtime_services.register_tasks(tasks)
        flow_event(
            "WORKER_DAG_REGISTERED",
            {
                "task_count": len(tasks),
                "runtime_persistence": self.runtime_services is not None,
                "tasks": [task.safe_for_coordinator() for task in tasks],
            },
            run_id=run_id,
        )
        flow_event(
            "WORKER_EXECUTION_STARTED",
            {
                "task_count": len(tasks),
                "parallel_execution_enabled": True,
            },
            run_id=run_id,
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
        flow_event(
            "WORKER_INITIAL_EXECUTION_COMPLETED",
            {
                "result_count": len(results),
                "execution_batches": batches,
                "timeline": timeline,
            },
            run_id=run_id,
        )

        # Execution-time forward replanning. Successful non-report WorkerResults
        # are frozen and reused. Only partial/failed/insufficient tasks are
        # superseded, and every patch remains inside the original GoalContract
        # and side-effect boundary.
        active_tasks = list(tasks)
        replan_audit: list[dict[str, Any]] = []
        invalid_replan_block_count = 0
        max_replan_rounds = 2
        for replan_round in range(1, max_replan_rounds + 1):
            observations = self._build_task_observations(active_tasks, results)
            flow_event(
                "WORKER_RESULT_OBSERVATION_COMPLETED",
                {
                    "replan_round": replan_round - 1,
                    "observations": observations,
                },
                run_id=run_id,
                level=(
                    "WARNING"
                    if any(not item.get("semantic_satisfied") for item in observations)
                    else "INFO"
                ),
            )
            blocking_context = _has_forward_replan_context_blocker(observations)
            replan_candidates = [
                item
                for item in observations
                if item.get("replan_recommended")
                and item.get("failure_kind") not in {
                    "worker_output_contract_failure",
                    "worker_output_contract_violation",
                    "completion_report_invalid",
                    "completion_report_missing",
                }
            ]
            if blocking_context or not replan_candidates:
                break
            before_unsatisfied = sum(
                1 for item in observations if not item.get("semantic_satisfied")
            )
            try:
                full_tasks, new_tasks, replan_meta = self.planner.replan_forward(
                    query=query,
                    request_mode=decision.mode.value,
                    session_id=session_id,
                    run_id=run_id,
                    user_id=user_id,
                    focus_refs=focus_refs,
                    context_refs=context_refs,
                    memory_summary=planning_memory_summary,
                    language=language,
                    as_of_time=explicit_as_of,
                    current_tasks=active_tasks,
                    current_results=results,
                    observations=observations,
                    replan_round=replan_round,
                )
            except Exception as exc:
                invalid_replan_block_count += 1
                audit = {
                    "round": replan_round,
                    "status": "blocked",
                    "reason": str(exc),
                    "exception_type": type(exc).__name__,
                    "observations": replan_candidates,
                }
                replan_audit.append(audit)
                flow_event(
                    "WORKER_FORWARD_REPLAN_BLOCKED",
                    audit,
                    run_id=run_id,
                    level="ERROR",
                )
                break
            if not new_tasks:
                replan_audit.append(
                    {
                        "round": replan_round,
                        "status": "no_patch",
                        "reason": "forward_replan_returned_no_new_tasks",
                        "meta": replan_meta,
                    }
                )
                break
            _bind_authoritative_task_context(full_tasks, entity_catalog=entity_catalog)
            _bind_authoritative_task_context(new_tasks, entity_catalog=entity_catalog)
            _bind_task_completion_contracts(full_tasks, directory=self.directory)
            _bind_task_completion_contracts(new_tasks, directory=self.directory)
            if self.runtime_services is not None:
                self.runtime_services.register_tasks(new_tasks)
            combined_results, new_batches, new_timeline = self._run_dag(
                new_tasks,
                query=query,
                output_dir=self.output_dir,
                db_path=self.db_path,
                default_top_k=default_top_k,
                language=language,
                execution_context=context,
                existing_results=results,
            )
            batch_offset = len(batches)
            for batch in new_batches:
                batch["batch_index"] = int(batch.get("batch_index") or 0) + batch_offset
                batch["replan_round"] = replan_round
            for row in new_timeline:
                row["replan_round"] = replan_round
            active_ids = {task.task_id for task in full_tasks}
            superseded_ids = sorted(set(results) - active_ids)
            results = {
                task_id: result
                for task_id, result in combined_results.items()
                if task_id in active_ids
            }
            active_tasks = list(full_tasks)
            batches.extend(new_batches)
            timeline.extend(new_timeline)
            after_observations = self._build_task_observations(active_tasks, results)
            after_unsatisfied = sum(
                1 for item in after_observations if not item.get("semantic_satisfied")
            )
            execution_progress = after_unsatisfied < before_unsatisfied

            # Structural progress describes whether the PlanPatch changed the
            # repair graph in a potentially useful way; execution progress says
            # whether that change actually satisfied more contracts after run.
            # Keep the two concepts separate so an executable repair is not
            # mislabeled merely because its newly added Worker later fails.
            prior_missing_slots = {
                str(slot)
                for item in replan_candidates
                for slot in item.get("missing_information_slots") or []
                if str(slot)
            }
            new_produced_slots = {
                str(slot)
                for task in new_tasks
                for slot in task.expected_output_slots
                if str(slot)
            }
            structural_progress = bool(
                new_tasks
                and (prior_missing_slots.intersection(new_produced_slots) or superseded_ids)
            )
            audit = {
                "round": replan_round,
                "status": "executed",
                "reused_task_ids": replan_meta.get("reused_task_ids") or [],
                "new_task_ids": replan_meta.get("new_task_ids") or [],
                "superseded_task_ids": superseded_ids,
                "before_unsatisfied": before_unsatisfied,
                "after_unsatisfied": after_unsatisfied,
                "structural_progress": structural_progress,
                "execution_progress": execution_progress,
                "progress": execution_progress,
                "meta": replan_meta,
            }
            replan_audit.append(audit)
            flow_event(
                "WORKER_FORWARD_REPLAN_EXECUTED",
                audit,
                run_id=run_id,
                level="INFO" if execution_progress else "WARNING",
            )
            if not execution_progress:
                break

        tasks = active_tasks
        final_observations = self._build_task_observations(tasks, results)
        flow_event(
            "WORKER_EXECUTION_COMPLETED",
            {
                "result_count": len(results),
                "execution_batches": batches,
                "timeline": timeline,
                "task_observations": final_observations,
                "replan_count": len([item for item in replan_audit if item.get("status") == "executed"]),
                "replan_audit": replan_audit,
            },
            run_id=run_id,
        )
        for result in results.values():
            for update in result.memory_updates:
                self.session_state.put(
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
        report = next(
            (
                results.get(task.task_id)
                for task in reversed(tasks)
                if task.assigned_agent == REPORT_WRITER and task.task_id in results
            ),
            None,
        )
        report_content = ""
        if report is not None and isinstance(report.data, dict):
            report_content = str(report.data.get("content") or "").strip()
            if not report_content and isinstance(report.data.get("slots"), dict):
                report_content = str(report.data["slots"].get("user_facing_report") or "").strip()
        goal_contract = dict(plan_meta.get("goal_contract") or {})
        goal_slots = {
            str(item) for item in [
                *(goal_contract.get("desired_outputs") or []),
                *(goal_contract.get("required_information_slots") or []),
            ] if str(item)
        }
        # Every normal Agent run owns a runtime-level N_FINAL requirement. A
        # missing report is therefore a terminal contract failure; Worker
        # summaries are audit material and must never become a second answer path.
        terminal_report_missing = not bool(report_content)
        if report_content:
            answer = report_content
        else:
            answer = (
                "最终自然语言报告未生成，系统不会用Worker状态摘要冒充业务回答。"
                if language != "en" else
                "The final user-facing report was not generated; Worker status summaries are not used as the business answer."
            )
        statuses = [result.status for result in results.values()]
        need_context = [item for result in results.values() for item in result.missing_items if item.blocking]
        status_failed = sum(status in {ResultStatus.FAILED, ResultStatus.BLOCKED, ResultStatus.NOT_EXECUTED} for status in statuses)
        semantic_failed = sum(
            1
            for item in final_observations
            if not item.get("semantic_satisfied")
            and item.get("failure_kind") != "context_missing"
        ) + (1 if terminal_report_missing else 0)
        if terminal_report_missing:
            final_observations.append({
                "task_id": "FINAL",
                "worker_id": "",
                "boundary_id": "result.composition",
                "status": "failed",
                "contract_valid": False,
                "completion_report_valid": False,
                "semantic_satisfied": False,
                "produced_information_slots": [],
                "missing_information_slots": ["user_facing_report"],
                "failure_kind": "terminal_user_facing_report_missing",
                "retryable": False,
                "repairable": True,
                "replan_recommended": True,
                "should_freeze": False,
                "reusable": False,
                "freeze_reason": "user_facing_report_required",
                "error": {
                    "code": "terminal_user_facing_report_missing",
                    "message": "Goal requires user_facing_report but no validated report content was produced.",
                    "component": "REPORT_WRITER",
                    "retryable": False,
                },
                "worker_escalation": None,
                "completion": {},
                "replan_triggers": ["required_contract_not_satisfied"],
            })
        failed = max(status_failed, semantic_failed)
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
        self.checkpoints.save(RunCheckpoint(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            status="waiting_user_input" if need_context else "completed" if success else "failed",
            current_node_id="final_response",
            capability_plan=dict(plan_meta.get("capability_plan") or {}),
            task_states={task.task_id: (results[task.task_id].status.value if task.task_id in results else "not_executed") for task in tasks},
            resolved_entity_refs=[ref.to_dict() for ref in focus_refs],
            slot_refs=[f"run-slot:{run_id}:{task_id}" for task_id in results],
            missing_context_slots=[item.key for item in need_context],
            replan_count=len([item for item in replan_audit if item.get("status") == "executed"]),
        ))
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
            "observations": final_observations,
            "replan_audit": replan_audit,
            "replan_count": len([item for item in replan_audit if item.get("status") == "executed"]),
            "invalid_replan_block_count": invalid_replan_block_count,
            "replan_limits": {"max_rounds": max_replan_rounds, "delegation_preserved": True},
            "agent_outputs": public_results,
            "agent_timeline": timeline,
            "handoff": {
                "handoff_available": bool(public_results),
                "handoff_count": len(public_results),
                "handoff_refs": [f"worker_result:{task_id}" for task_id in public_results],
                "safety": {"worker_private_tools": True, "coordinator_tool_visibility": "none"},
            },
            "graph_runtime": {
                "contract_version": "capability_contract_runtime.v1",
                "graph_id": self.store.graph_id,
                "task_contract": "capability_execution_task.v1",
                "result_contract": "graph_worker_result.v1",
                "focus_refs": [ref.to_dict() for ref in focus_refs],
                "resolution_audit": resolution_audit,
                "planner": plan_meta,
                "worker_dag": {
                    "contract_version": "worker_dag_snapshot.v1",
                    "task_count": len(tasks),
                    "tasks": [task.safe_for_coordinator() for task in tasks],
                    "execution_batches": batches,
                    "execution_order": [
                        item.task_id for item in tasks if item.task_id in results
                    ],
                },
                "runtime_persistence": {
                    "agent_steps_connected": self.runtime_services is not None,
                    "runtime_layer": "capability_dag+worker_tool_dag",
                },
            },
        }

    @staticmethod
    def _task_observation(
        task: GraphAgentTask,
        result: GraphWorkerResult | None,
    ) -> dict[str, Any]:
        expected_slots = set(task.expected_output_slots)
        if result is None:
            return {
                "task_id": task.task_id,
                "worker_id": task.worker_id,
                "boundary_id": task.boundary_id,
                "status": ResultStatus.NOT_EXECUTED.value,
                "contract_valid": False,
                "semantic_satisfied": False,
                "produced_information_slots": [],
                "missing_information_slots": sorted(expected_slots),
                "failure_kind": "not_executed",
                "retryable": False,
                "repairable": True,
                "replan_recommended": True,
                "should_freeze": False,
                "reusable": False,
                "freeze_reason": "task_not_executed",
                "completion": {},
            }
        completion = dict(result.completion or {})
        completion_valid = False
        completion_error = ""
        if completion:
            try:
                validate_completion_report(completion, task)
                completion_valid = True
            except Exception as exc:
                completion_error = str(exc)
        produced = {
            str(item) for item in completion.get("produced_information_slots") or [] if str(item)
        }
        missing = {
            str(item) for item in completion.get("missing_information_slots") or [] if str(item)
        } or (expected_slots - produced)
        if completion_valid:
            decision = flow_decision(
                result.status,
                completion,
                output_type=result.output_type,
                retryable=bool((result.error or {}).get("retryable")),
            )
            semantic_satisfied = bool(decision.semantic_satisfied)
            failure_kind = decision.failure_kind
            repairable = bool(decision.replan_recommended)
            should_freeze = bool(decision.should_freeze)
            reusable = bool(decision.reusable)
            freeze_reason = decision.freeze_reason
        else:
            semantic_satisfied = False
            failure_kind = "completion_report_invalid" if completion_error else "completion_report_missing"
            repairable = result.status != ResultStatus.NEED_CONTEXT
            should_freeze = False
            reusable = False
            freeze_reason = "capability_contract_completion_required"
        escalation = dict((result.metadata or {}).get("worker_escalation") or {})
        error = escalation or dict(result.error or {})
        if escalation:
            failure_kind = str(escalation.get("error_id") or failure_kind)
            repairable = bool(
                (result.metadata or {}).get("worker_escalation_retryable", repairable)
            )
        if completion_error and not error:
            error = {
                "code": "capability_completion_report_invalid",
                "message": completion_error,
                "component": result.agent_id,
                "retryable": False,
            }
        return {
            "task_id": task.task_id,
            "worker_id": task.worker_id,
            "boundary_id": task.boundary_id,
            "status": result.status.value,
            "contract_valid": completion_valid,
            "completion_report_valid": completion_valid,
            "semantic_satisfied": semantic_satisfied,
            "produced_information_slots": sorted(produced),
            "missing_information_slots": sorted(missing),
            "failure_kind": failure_kind,
            "retryable": bool((result.error or {}).get("retryable")),
            "repairable": repairable,
            "replan_recommended": bool(not semantic_satisfied and repairable),
            "should_freeze": should_freeze,
            "reusable": reusable,
            "freeze_reason": freeze_reason,
            "error": error or None,
            "worker_escalation": escalation or None,
            "completion": completion,
            "replan_triggers": ([] if semantic_satisfied else ["required_contract_not_satisfied"]),
        }

    @classmethod
    def _build_task_observations(
        cls,
        tasks: list[GraphAgentTask],
        results: dict[str, GraphWorkerResult],
    ) -> list[dict[str, Any]]:
        return [
            cls._task_observation(task, results.get(task.task_id))
            for task in tasks
        ]

    @staticmethod
    def _worker_result_usable(result: GraphWorkerResult | None) -> bool:
        """Return whether a dependency may unlock its downstream Worker."""

        if result is None:
            return False
        completion = dict(result.completion or {})
        return bool(
            completion
            and completion.get("expected_task_completed")
            and completion.get("completion_status") == "completed"
            and result.status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
        )

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
        existing_results: dict[str, GraphWorkerResult] | None = None,
    ) -> tuple[dict[str, GraphWorkerResult], list[dict[str, Any]], list[dict[str, Any]]]:
        results: dict[str, GraphWorkerResult] = dict(existing_results or {})
        pending = {task.task_id: task for task in tasks}
        dag_wait_started = time.perf_counter()
        batches: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []
        batch_index = 0
        while pending:
            # A failed dependency pauses the downstream branch. The blocked
            # Workers are not executed with invalid/empty upstream results; their
            # structured BLOCKED results are reported to MainAgent for replan.
            blocked_rows: list[dict[str, Any]] = []
            propagated = True
            while propagated:
                propagated = False
                for task_id, task in list(pending.items()):
                    blocked_by = [
                        dependency_id
                        for dependency_id in task.dependency_task_ids
                        if dependency_id in results
                        and not self._worker_result_usable(results.get(dependency_id))
                    ]
                    if not blocked_by:
                        continue
                    upstream_repairable = any(
                        bool((results.get(dependency_id).metadata or {}).get("replan_recommended"))
                        or bool((results.get(dependency_id).error or {}).get("retryable"))
                        for dependency_id in blocked_by
                        if results.get(dependency_id) is not None
                    )
                    task.metadata.setdefault(
                        "dependency_wait_ms",
                        round((time.perf_counter() - dag_wait_started) * 1000.0, 3),
                    )
                    result = GraphWorkerResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                        status=ResultStatus.BLOCKED,
                        output_type=task.expected_output_type,
                        data=None,
                        error={
                            "code": "upstream_worker_failed",
                            "message": "上游 Worker 执行失败，当前任务已暂停并等待 MainAgent 重规划。",
                            "component": "worker_dag_executor",
                            "retryable": upstream_repairable,
                            "blocked_by_task_ids": sorted(blocked_by),
                        },
                        focus_refs=task.focus_refs,
                        summary="上游 Worker 执行失败，当前 Worker 未执行并等待重规划。",
                        warnings=["blocked_by_upstream_worker_failure"],
                        completion=non_success_completion_report(
                            task,
                            execution_status="blocked",
                            reason="Upstream Worker failed; this Worker was not executed.",
                            failure_kind="upstream_worker_failed",
                        ),
                        metadata={
                            "blocked_by_task_ids": sorted(blocked_by),
                            "replan_required": upstream_repairable,
                        },
                    )
                    results[task.task_id] = result
                    if self.runtime_services is not None:
                        self.runtime_services.record_result(task, result)
                    try:
                        published = self.slot_store.publish_worker_result(task, result)
                        if published:
                            flow_event(
                                "WORKER_SLOTS_PUBLISHED",
                                {
                                    "task_id": task.task_id,
                                    "worker_id": task.worker_id,
                                    "slot_ids": [record.slot_id for record in published],
                                    "value_refs": [record.value_ref for record in published],
                                },
                                run_id=task.run_id,
                            )
                    except Exception as exc:
                        trace_exception(
                            "coordinator.slot_publish.failed", exc,
                            run_id=task.run_id, task_id=task.task_id,
                        )
                    timeline.append({
                        "task_id": task.task_id,
                        "worker_id": task.worker_id,
                        "agent_id": task.assigned_agent,
                        "boundary_id": task.boundary_id,
                        "status": result.status.value,
                        "output_type": result.output_type,
                        "duration_ms": 0.0,
                        "dependency_wait_ms": task.metadata.get("dependency_wait_ms", 0.0),
                        "summary": result.summary[:500],
                        "warning_count": len(result.warnings),
                        "evidence_count": 0,
                        "artifact_count": 0,
                        "error": result.error,
                    })
                    pending.pop(task_id, None)
                    blocked_rows.append({
                        "task_id": task_id,
                        "blocked_by_task_ids": sorted(blocked_by),
                    })
                    propagated = True
            if blocked_rows:
                flow_event(
                    "WORKER_DAG_PAUSED_FOR_REPLAN",
                    {
                        "blocked_tasks": blocked_rows,
                        "reason": "upstream_worker_failed",
                    },
                    run_id=str(tasks[0].run_id if tasks else ""),
                    level="WARNING",
                )
            if not pending:
                break

            ready = [
                task
                for task in pending.values()
                if all(
                    dependency_id in results
                    and self._worker_result_usable(results.get(dependency_id))
                    for dependency_id in task.dependency_task_ids
                )
            ]
            if not ready:
                for task in list(pending.values()):
                    task.metadata.setdefault(
                        "dependency_wait_ms",
                        round((time.perf_counter() - dag_wait_started) * 1000.0, 3),
                    )
                    result = GraphWorkerResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                        status=ResultStatus.NOT_EXECUTED,
                        output_type=task.expected_output_type,
                        data=None,
                        error={
                            "code": "unresolved_task_dependency",
                            "message": "任务依赖无法满足。",
                            "component": "worker_dag_executor",
                            "retryable": False,
                        },
                        focus_refs=task.focus_refs,
                        summary="任务依赖无法满足。",
                        warnings=["unresolved_task_dependency"],
                    )
                    results[task.task_id] = result
                    pending.pop(task.task_id, None)
                    if self.runtime_services is not None:
                        self.runtime_services.record_result(task, result)
                break
            ready_at = time.perf_counter()
            for task in ready:
                task.metadata.setdefault(
                    "dependency_wait_ms",
                    round((ready_at - dag_wait_started) * 1000.0, 3),
                )
            batch_index += 1
            batches.append({
                "batch_index": batch_index,
                "task_ids": [task.task_id for task in ready],
                "agents": [task.assigned_agent for task in ready],
                "parallel": len(ready) > 1,
            })
            max_workers = min(4, len(ready))
            if self.runtime_services is not None:
                for task in ready:
                    self.runtime_services.mark_ready(task)
                    self.runtime_services.mark_running(task)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        self.specialist.run,
                        task,
                        current_user_request=query,
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
                            output_type=task.expected_output_type,
                            data=None,
                            error={
                                "code": "worker_execution_failed",
                                "message": str(exc),
                                "component": task.assigned_agent,
                                "retryable": True,
                            },
                            focus_refs=task.focus_refs,
                            summary="Worker 执行失败。",
                            warnings=[f"{type(exc).__name__}:{exc}"],
                        )
                    results[task.task_id] = result
                    if self.runtime_services is not None:
                        self.runtime_services.record_result(task, result)
                    try:
                        published = self.slot_store.publish_worker_result(task, result)
                        if published:
                            flow_event(
                                "WORKER_SLOTS_PUBLISHED",
                                {
                                    "task_id": task.task_id,
                                    "worker_id": task.worker_id,
                                    "slot_ids": [record.slot_id for record in published],
                                    "value_refs": [record.value_ref for record in published],
                                },
                                run_id=task.run_id,
                            )
                    except Exception as exc:
                        trace_exception(
                            "coordinator.slot_publish.failed", exc,
                            run_id=task.run_id, task_id=task.task_id,
                        )
                    timeline.append({
                        "task_id": task.task_id,
                        "worker_id": task.worker_id,
                        "agent_id": task.assigned_agent,
                        "boundary_id": task.boundary_id,
                        "status": result.status.value,
                        "output_type": result.output_type,
                        "duration_ms": result.metadata.get("duration_ms"),
                        "dependency_wait_ms": result.metadata.get(
                            "dependency_wait_ms", task.metadata.get("dependency_wait_ms", 0.0)
                        ),
                        "llm_execution_timing": result.metadata.get("llm_execution_timing", {}),
                        "tool_execution_timing": result.metadata.get("tool_execution_timing", {}),
                        "unattributed_worker_execution_ms": result.metadata.get(
                            "unattributed_worker_execution_ms", 0.0
                        ),
                        "summary": result.summary[:500],
                        "warning_count": len(result.warnings),
                        "evidence_count": len(result.evidence_refs),
                        "artifact_count": len(result.artifact_refs),
                        "error": result.error,
                    })
                    pending.pop(task.task_id, None)
        return results, batches, timeline

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

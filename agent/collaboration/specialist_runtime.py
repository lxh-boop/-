"""Worker execution facade for the capability-contract runtime."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.capabilities import CapabilityContract, CapabilityContractValidator
from agent.capabilities.semantic_slots import SemanticSlotError
from agent.communication import MessageType, publish_agent_message
from agent.console_trace import flow_event, get_llm_execution_timing, get_tool_execution_timing
from agent.graph.impact_service import GraphImpactService
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.llm_audit import activate_llm_audit_context
from agent.tool_dag import ToolDagExecutor, ToolDagValidator, WorkerToolDagPlanner, WorkerToolDagRuntime
from agent.tool_runtime import ToolExecutor
from agent.runtime_state import RunSlotStore
from agent.worker_tools import WorkerToolDirectory, build_worker_tool_registry

from .context_projection import WorkerInputProjectionMiddleware
from .worker_directory import (
    CapabilityWorkerDirectory,
    DATABASE_WRITER,
    ENTITY_ANALYST,
    EVIDENCE_COLLECTOR,
    GRAPH_RELATION_RETRIEVER,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from .error_contracts import escalation_from_worker_result
from .completion import canonicalize_completion_report, flow_decision, non_success_completion_report, runtime_completion_report
from .models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus, TaskStatus
from .workers import (
    run_diagnostic,
    run_evidence,
    run_entity_analysis,
    run_graph_context,
    run_graph_impact,
    run_internal_system,
    run_report_writer,
    run_risk,
    run_strategy_guard,
)
from .workers.common import dependency_results as _dependency_results
from .workers.common import refs_from_dependencies as _refs_from_dependencies
from .workers.common import safe_public_value as _safe
from .workers.slot_inputs import missing_contract_required_slot_ids


class SpecialistRuntime:
    """Execute one Worker-selected capability task.

    Worker selection is already complete.  This layer exposes only the assigned
    Worker's private tools, resolves declared slot bindings, executes the domain
    Worker and validates every contract in the task's contract list.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        provider: GraphProviderAdapter,
        impact_service: GraphImpactService,
        slot_store: RunSlotStore,
        directory: CapabilityWorkerDirectory | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.provider = provider
        self.impact_service = impact_service
        self.directory = directory or CapabilityWorkerDirectory()
        self.input_projection = WorkerInputProjectionMiddleware(slot_store)
        self.worker_tool_registry = build_worker_tool_registry(
            provider=provider,
            impact_service=impact_service,
        )
        self.worker_tool_directory = WorkerToolDirectory(self.worker_tool_registry)
        self.worker_tool_executor = ToolExecutor(registry=self.worker_tool_registry)
        validator = ToolDagValidator(self.worker_tool_registry, self.worker_tool_directory)
        planner = WorkerToolDagPlanner(
            llm_service=self.llm_service,
            directory=self.worker_tool_directory,
            validator=validator,
        )
        self.worker_tool_dag_runtime = WorkerToolDagRuntime(
            planner=planner,
            executor=ToolDagExecutor(self.worker_tool_executor, max_parallel=4),
        )
        self.contract_validator = CapabilityContractValidator()

    @staticmethod
    def _produced_slots(task: GraphAgentTask, result: GraphWorkerResult) -> list[str]:
        del task
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        materialized = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        return list(dict.fromkeys(
            str(slot_id) for slot_id, value in materialized.items()
            if str(slot_id) and value is not None
        ))

    def run(
        self,
        task: GraphAgentTask,
        *,
        current_user_request: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None = None,
    ) -> GraphWorkerResult:
        started = time.perf_counter()
        context = dict(execution_context or {})
        context.update({
            "current_user_request": current_user_request,
            "language": language,
        })
        activate_llm_audit_context(
            run_id=task.run_id,
            conversation_id=task.session_id,
            output_dir=output_dir,
            formal_entry_used=True,
            formal_entry_name="agent.collaboration.specialist_runtime",
            task_id=task.task_id,
            worker_id=task.worker_id,
            agent_id=task.assigned_agent,
        )
        task.status = TaskStatus.RUNNING
        try:
            resolved_inputs, projected_inputs = self.input_projection.project(
                task, execution_context=context
            )
        except SemanticSlotError as exc:
            task.status = TaskStatus.FAILED
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                output_type="CapabilityResult",
                data=None,
                error={
                    "error_id": "contract_validation_failure",
                    "code": exc.code,
                    "message": str(exc),
                    "component": "worker_input_projection",
                    "retryable": False,
                    "slot_id": exc.slot_id,
                    "detail": exc.detail,
                },
                focus_refs=task.focus_refs,
                summary=(
                    "CapabilityContract要求的Slot字段不存在，Worker未执行。"
                    if language != "en"
                    else "A required Slot field is missing; the Worker was not executed."
                ),
                completion=non_success_completion_report(
                    task,
                    execution_status="failed",
                    reason=str(exc),
                    failure_kind="contract_validation_failure",
                ),
                metadata={
                    "input_gate_owner": "runtime",
                    "main_agent_replan_recommended": False,
                },
            )
        flow_event(
            "WORKER_INPUT_PROJECTED",
            {
                "task_id": task.task_id,
                "worker_id": task.worker_id,
                "slot_ids": [item.slot_id for item in projected_inputs],
                "upstream_value_refs": [item.value_ref for item in projected_inputs if item.value_ref],
                "projection_mode": "slot_store_field_projected",
                "coordinator_summary_used_as_execution_input": False,
                "slot_projection": [
                    {
                        "slot_id": item.slot_id,
                        "required_paths": item.required_paths,
                        "optional_paths": item.optional_paths,
                        "raw_chars": item.raw_chars,
                        "projected_chars": item.projected_chars,
                        "raw_token_estimate": item.raw_token_estimate,
                        "projected_token_estimate": item.projected_token_estimate,
                    }
                    for item in projected_inputs
                ],
                "raw_token_estimate_total": sum(item.raw_token_estimate for item in projected_inputs),
                "projected_token_estimate_total": sum(item.projected_token_estimate for item in projected_inputs),
            },
            run_id=task.run_id,
        )
        for item in projected_inputs:
            if item.projected_token_estimate > 8000:
                flow_event(
                    "SLOT_OVERSIZED",
                    {
                        "task_id": task.task_id,
                        "worker_id": task.worker_id,
                        "slot_id": item.slot_id,
                        "raw_token_estimate": item.raw_token_estimate,
                        "projected_token_estimate": item.projected_token_estimate,
                        "required_paths": item.required_paths,
                    },
                    run_id=task.run_id,
                )
        projected_total = sum(item.projected_token_estimate for item in projected_inputs)
        if projected_total > 16000:
            flow_event(
                "WORKER_INPUT_OVERSIZED",
                {
                    "task_id": task.task_id,
                    "worker_id": task.worker_id,
                    "projected_token_estimate_total": projected_total,
                    "slot_ids": [item.slot_id for item in projected_inputs],
                },
                run_id=task.run_id,
            )

        # Input sufficiency is a Runtime responsibility, not a Worker judgment.
        # A Worker receives only the inputs that were actually bound to its
        # CapabilityContract.  Missing contract-required bindings are stopped
        # here before the domain Worker is invoked; unbound non-required slots
        # are simply outside that Worker's world view.  Empty containers are
        # valid bound values (e.g. explicit business_empty) and only None counts
        # as absent.
        missing_required = sorted(
            missing_contract_required_slot_ids(task, resolved_inputs)
        )
        if missing_required:
            task.status = TaskStatus.WAITING_CONTEXT
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                output_type="CapabilityResult",
                data=None,
                error={
                    "error_id": "missing_context",
                    "operation": task.objective or task.boundary_id,
                    "reason": "CapabilityContract required input bindings are unavailable.",
                },
                focus_refs=task.focus_refs,
                summary=(
                    "Runtime未能绑定CapabilityContract要求的输入。"
                    if language != "en"
                    else "Runtime could not bind required CapabilityContract inputs."
                ),
                missing_items=[
                    MissingContextItem(
                        key=slot_id,
                        description=f"CapabilityContract required input is not bound: {slot_id}",
                        expected_format="Runtime SlotBinder input slot",
                        searched_sources=["resolved_input_bindings", "resolved_inputs"],
                    )
                    for slot_id in missing_required
                ],
                completion=non_success_completion_report(
                    task,
                    execution_status="need_context",
                    reason="CapabilityContract required input bindings are unavailable.",
                    failure_kind="missing_context",
                ),
            )
            produced = self._produced_slots(task, result)
            result.metadata.update({
                "boundary_id": task.boundary_id,
                "attempt": task.attempt,
                "resolved_input_slots": sorted(resolved_inputs),
                "produced_information_slots": produced,
                "input_gate_owner": "runtime",
            })
            decision = flow_decision(
                result.status,
                result.completion,
                output_type=result.output_type,
                retryable=False,
            )
            result.status = decision.result_status
            result.metadata.update({
                "semantic_satisfied": decision.semantic_satisfied,
                "should_freeze": decision.should_freeze,
                "reusable": decision.reusable,
                "replan_recommended": decision.replan_recommended,
                "failure_kind": decision.failure_kind,
                "freeze_reason": decision.freeze_reason,
            })
            return result

        card = self.directory.get(task.worker_id or task.assigned_agent)
        allowed_tools = list(task.metadata.get("allowed_tool_ids") or getattr(card, "private_tool_ids", []) or [])

        try:
            if task.assigned_agent == EVIDENCE_COLLECTOR:
                result = run_evidence(
                    self.worker_tool_dag_runtime, task, current_user_request,
                    output_dir, db_path, default_top_k,
                    worker_prompt=str(card.private_worker_prompt or ""),
                    allowed_tool_names=allowed_tools,
                )
            elif task.assigned_agent == PORTFOLIO_ANALYST:
                result = run_internal_system(
                    self.worker_tool_dag_runtime, task, output_dir, db_path, default_top_k,
                    worker_prompt=str(card.private_worker_prompt or ""),
                    allowed_tool_names=allowed_tools,
                    provider=self.provider,
                )
            elif task.assigned_agent == DATABASE_WRITER:
                result = run_graph_context(
                    self.worker_tool_executor, task, output_dir, db_path,
                    resolved_inputs=resolved_inputs,
                )
            elif task.assigned_agent == ENTITY_ANALYST:
                result = run_entity_analysis(
                    self.llm_service, task,
                    resolved_inputs=resolved_inputs, language=language,
                )
            elif task.assigned_agent == GRAPH_RELATION_RETRIEVER:
                result = run_graph_impact(
                    self.worker_tool_dag_runtime, task,
                    resolved_inputs=resolved_inputs,
                    worker_prompt=str(card.private_worker_prompt or ""),
                    allowed_tool_names=allowed_tools,
                    output_dir=output_dir,
                    db_path=db_path,
                )
            elif task.assigned_agent == RISK_ANALYST:
                result = run_risk(
                    self.llm_service, self.worker_tool_dag_runtime, task,
                    output_dir, db_path,
                    resolved_inputs=resolved_inputs,
                    worker_prompt=str(card.private_worker_prompt or ""),
                    allowed_tool_names=allowed_tools,
                    language=language,
                )
            elif task.assigned_agent == STRATEGY_GUARD:
                result = run_strategy_guard(
                    self.llm_service, task,
                    current_user_request=current_user_request,
                    resolved_inputs=resolved_inputs,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    language=language,
                    execution_context=context,
                )
            elif task.assigned_agent == REPORT_WRITER:
                result = run_report_writer(
                    self.llm_service, task, language,
                    resolved_inputs=resolved_inputs,
                )
            elif task.assigned_agent == SYSTEM_DIAGNOSTIC:
                result = run_diagnostic(self.provider, task)
            else:
                raise RuntimeError(f"unknown_worker_agent:{task.assigned_agent}")
        except Exception as exc:
            exc_name = type(exc).__name__
            structured_output_failure = exc_name == "LLMJSONError" or "json" in exc_name.lower()
            failure_kind = (
                "structured_output_failure"
                if structured_output_failure
                else "worker_execution_failure"
            )
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                output_type="CapabilityResult",
                data=None,
                error={
                    "code": failure_kind,
                    "message": str(exc),
                    "component": task.assigned_agent,
                    "retryable": False if structured_output_failure else True,
                    "local_recovery_exhausted": bool(structured_output_failure),
                },
                focus_refs=task.focus_refs,
                summary=(
                    "Worker结构化输出修复失败。"
                    if structured_output_failure and language != "en"
                    else "Worker structured-output recovery failed."
                    if structured_output_failure
                    else "Worker 执行失败."
                    if language != "en"
                    else "Worker execution failed."
                ),
                warnings=[f"{exc_name}:{exc}"],
                completion=non_success_completion_report(
                    task,
                    execution_status="failed",
                    reason=str(exc),
                    failure_kind=failure_kind,
                ),
                metadata={
                    "main_agent_replan_recommended": not structured_output_failure,
                    "structured_output_local_recovery": (
                        "exhausted" if structured_output_failure else ""
                    ),
                },
            )

        produced = self._produced_slots(task, result)
        result.metadata.update({
            "boundary_id": task.boundary_id,
            "attempt": task.attempt,
            "resolved_input_slots": sorted(resolved_inputs),
            "produced_information_slots": produced,
        })
        if not result.completion:
            result.completion = runtime_completion_report(
                task,
                result_status=result.status,
                output_type=result.output_type,
                data=result.data,
                error=result.error,
            )

        contracts = [CapabilityContract.from_dict(item) for item in task.contracts]
        materialized_slots = (
            dict((result.data or {}).get("slots") or {})
            if isinstance(result.data, dict) and isinstance((result.data or {}).get("slots"), dict)
            else {}
        )
        contract_reports = self.contract_validator.validate(
            contracts=contracts,
            produced_slots=set(produced),
            materialized_slots=materialized_slots,
            result_status=result.status.value,
            result_payload=result.data,
            evidence_refs=[ref.node_id for ref in result.evidence_refs] or [f"worker_result:{task.task_id}"],
        )
        result.status, result.completion, satisfied = canonicalize_completion_report(
            task,
            result_status=result.status,
            completion=result.completion,
            contract_reports=contract_reports,
            produced_slots=produced,
            result_data=result.data,
        )
        if satisfied:
            # Contract validation is authoritative. Clear stale local errors or
            # limitations left by an unnecessary Tool-DAG replan.
            result.error = None
            result.missing_items = []
            result.warnings = [
                item for item in result.warnings
                if not str(item).startswith((
                    "worker_local_handling_exhausted",
                    "worker_private_tool_exhausted",
                ))
            ]
            if "未能完成" in result.summary or "failed" in result.summary.lower():
                result.summary = "Worker已完成合同要求的信息槽位。"
        decision = flow_decision(
            result.status,
            result.completion,
            output_type=result.output_type,
            retryable=bool((result.error or {}).get("retryable")),
        )
        result.status = decision.result_status
        result.metadata.update({
            "semantic_satisfied": decision.semantic_satisfied,
            "should_freeze": decision.should_freeze,
            "reusable": decision.reusable,
            "replan_recommended": decision.replan_recommended,
            "failure_kind": decision.failure_kind,
            "freeze_reason": decision.freeze_reason,
        })

        escalation = escalation_from_worker_result(task, result)
        if escalation is not None:
            # Worker-local recovery is already exhausted at this point. Preserve
            # whether the owning Worker considers a MainAgent-level retry useful
            # before replacing the public error with the safe escalation contract.
            result.metadata["worker_escalation_retryable"] = bool(
                (result.error or {}).get("retryable")
            )
            # Private Tool/LLM details stay private. MainAgent receives only this
            # capability-level error contract, never raw arguments or traces.
            result.error = escalation.to_dict()
            result.metadata["worker_escalation"] = escalation.to_dict()

        result.metadata["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        llm_timing = get_llm_execution_timing(task.run_id, task.task_id)
        tool_timing = get_tool_execution_timing(task.run_id, task.task_id)
        result.metadata["llm_execution_timing"] = llm_timing
        result.metadata["tool_execution_timing"] = tool_timing
        result.metadata["unattributed_worker_execution_ms"] = round(max(
            0.0,
            float(result.metadata["duration_ms"])
            - float(llm_timing.get("provider_transport_ms_sum") or 0.0)
            - float(tool_timing.get("wall_duration_ms") or 0.0),
        ), 3)

        publish_agent_message(
            output_dir=output_dir,
            user_id=task.user_id,
            conversation_id=task.session_id,
            run_id=task.run_id,
            task_id=task.task_id,
            sender=task.assigned_agent,
            receiver="COORDINATOR",
            message_type=MessageType.WORKER_RESULT_AVAILABLE,
            payload={
                "status": result.status.value,
                "output_type": result.output_type,
                "summary": result.summary[:500],
                "boundary_id": task.boundary_id,
                "produced_information_slots": produced,
                "expected_task_completed": bool(result.completion.get("expected_task_completed")),
            },
            payload_schema="capability_worker_result_available.v1",
            context_refs=[ref.to_dict() for ref in result.focus_refs[:20]],
            artifact_refs=list(result.artifact_refs[:20]),
            source_refs=[ref.to_dict() for ref in result.evidence_refs[:20]],
            warnings=list(result.warnings[:10]),
            error=dict(result.error or {}),
            metadata={"worker_id": task.worker_id, "boundary_id": task.boundary_id},
        )
        task.status = (
            TaskStatus.COMPLETED if result.status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
            else TaskStatus.PARTIAL if result.status == ResultStatus.PARTIAL
            else TaskStatus.WAITING_CONTEXT if result.status == ResultStatus.NEED_CONTEXT
            else TaskStatus.FAILED
        )
        return result


__all__ = ["SpecialistRuntime", "_dependency_results", "_refs_from_dependencies", "_safe"]

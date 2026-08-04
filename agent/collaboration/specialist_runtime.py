"""Coordinator-facing facade for executing one assigned specialist task.

This module owns Worker dispatch, common error handling, task-status transitions,
and execution metadata. Domain behavior lives in ``agent.collaboration.workers``;
this facade does not plan tasks, choose Workers, or expose private tools.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.llm import LLMService

from agent.communication import MessageType, publish_agent_message

from agent.graph.impact_service import GraphImpactService
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.tool_runtime import ToolExecutor
from agent.tool_dag import (
    ToolDagExecutor,
    ToolDagValidator,
    WorkerToolDagPlanner,
    WorkerToolDagRuntime,
)
from agent.worker_tools import WorkerToolDirectory, build_worker_tool_registry

from .completion import flow_decision, non_success_completion_report, runtime_completion_report
from .agent_directory import (
    AgentDirectory,
    EVIDENCE_COLLECTOR,
    ENTITY_ANALYST,
    DATABASE_WRITER,
    GRAPH_RELATION_RETRIEVER,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from .models import AccessMode, GraphAgentTask, GraphWorkerResult, ResultStatus, TaskStatus
from .worker_contracts import WorkerContractViolation
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


def _contract_violation_from_chain(exc: BaseException) -> WorkerContractViolation | None:
    """Return a Worker contract violation wrapped by the LLM repair boundary.

    ``LLMService.generate_json`` performs the Worker's single targeted repair and
    raises ``LLMJSONError`` from the second validation exception when repair still
    fails.  Keeping the original violation classification prevents a local output
    repair failure from being misrouted as a MainAgent Worker-selection failure.
    """

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if isinstance(current, WorkerContractViolation):
            return current
        for linked in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(linked, BaseException):
                pending.append(linked)
    return None


class SpecialistRuntime:
    """Dispatch Worker tasks to domain-scoped executors.

    The class remains the stable coordinator-facing facade. Worker implementation
    details live in ``agent.collaboration.workers`` and retain the existing
    GraphAgentTask/GraphWorkerResult contracts.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        provider: GraphProviderAdapter,
        impact_service: GraphImpactService,
        directory: AgentDirectory | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.provider = provider
        self.impact_service = impact_service
        self.directory = directory or AgentDirectory()
        self.worker_tool_registry = build_worker_tool_registry(provider=provider)
        self.worker_tool_directory = WorkerToolDirectory(
            self.worker_tool_registry
        )
        self.worker_tool_executor = ToolExecutor(
            registry=self.worker_tool_registry
        )
        self.worker_tool_dag_validator = ToolDagValidator(
            self.worker_tool_registry,
            self.worker_tool_directory,
        )
        self.worker_tool_dag_planner = WorkerToolDagPlanner(
            llm_service=self.llm_service,
            directory=self.worker_tool_directory,
            validator=self.worker_tool_dag_validator,
        )
        self.worker_tool_dag_executor = ToolDagExecutor(
            self.worker_tool_executor,
            max_parallel=4,
        )
        self.worker_tool_dag_runtime = WorkerToolDagRuntime(
            planner=self.worker_tool_dag_planner,
            executor=self.worker_tool_dag_executor,
        )

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
        resolved_inputs: dict[str, Any] = {}
        task_contract = None

        # The registered contract owns required fields and completion-report
        # structure. Planner metadata may enable stricter input binding, but it
        # never decides whether completion semantics exist.
        try:
            card = self.directory.get(task.worker_id or task.assigned_agent)
            task_contract = card.task_contract(task.task_type)
        except KeyError:
            card = None

        if task_contract is not None:
            task.completion_contract = self.directory.completion_contract_for_task(task)

        try:
            if task_contract is not None:
                task_access = AccessMode.from_value(task_contract.access_mode)
                goal_access = AccessMode.from_value(
                    dict(task.metadata.get("goal_contract") or {}).get("access_mode")
                )
                if task_access == AccessMode.WRITE and goal_access != AccessMode.WRITE:
                    raise WorkerContractViolation(
                        "write_worker_not_authorized",
                        "$.completion_contract.access_mode",
                        task.worker_id or task.assigned_agent,
                    )
            if task_contract is not None and task.metadata.get("structured_worker_contract"):
                self.directory.validate_task_contract(task)
                resolved_inputs = self.directory.resolve_task_inputs(task, dependency_results)

            if task.assigned_agent == EVIDENCE_COLLECTOR:
                result = self._run_evidence(task, current_user_request, output_dir, db_path, default_top_k)
            elif task.assigned_agent == PORTFOLIO_ANALYST:
                result = self._run_internal_system(task, output_dir, db_path, default_top_k)
            elif task.assigned_agent == DATABASE_WRITER:
                result = self._run_graph_context(task, resolved_inputs, output_dir, db_path)
            elif task.assigned_agent == ENTITY_ANALYST:
                result = self._run_entity_analysis(task, dependency_results, resolved_inputs, language)
            elif task.assigned_agent == GRAPH_RELATION_RETRIEVER:
                result = self._run_graph_impact(task, dependency_results, resolved_inputs)
            elif task.assigned_agent == RISK_ANALYST:
                result = self._run_risk(
                    task, dependency_results, resolved_inputs, output_dir, db_path, language
                )
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
                result = self._run_report_writer(task, dependency_results, resolved_inputs, language)
            elif task.assigned_agent == SYSTEM_DIAGNOSTIC:
                result = self._run_diagnostic(task)
            else:
                result = GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.NOT_EXECUTED,
                    output_type=task.expected_output_type,
                    data=None,
                    error={
                        "code": "unknown_worker_agent",
                        "message": f"Unsupported Worker agent: {task.assigned_agent}",
                        "retryable": False,
                    },
                    focus_refs=task.focus_refs,
                    summary=f"Unsupported Worker agent: {task.assigned_agent}",
                    warnings=["unknown_worker_agent"],
                )
        except Exception as exc:
            contract_violation = _contract_violation_from_chain(exc)
            violation_code = str(getattr(contract_violation, "code", "") or "")
            output_contract_failure = bool(
                contract_violation is not None
                and violation_code in {
                    "report_output_validation_failed",
                    "completion_report_version_mismatch",
                    "completion_output_type_mismatch",
                    "completion_report_unknown_information_slot",
                    "completion_report_slot_overlap",
                    "completion_report_slot_partition_incomplete",
                    "completion_report_criteria_mismatch",
                    "completed_report_requires_completed_status",
                    "completed_report_cannot_have_missing_slots",
                    "completed_report_requires_all_criteria",
                    "incomplete_report_cannot_use_completed_status",
                }
            )
            error_code = (
                "worker_output_contract_failure"
                if output_contract_failure
                else "worker_contract_violation"
                if contract_violation is not None
                else "worker_execution_failed"
            )
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                output_type=task.expected_output_type,
                data=None,
                error={
                    "code": error_code,
                    "message": str(exc),
                    "component": task.assigned_agent,
                    "retryable": contract_violation is None,
                },
                focus_refs=task.focus_refs,
                summary=(
                    "Worker 输入合同或专业数据链路执行失败。"
                    if language != "en"
                    else "The Worker input contract or specialist data path failed."
                ),
                warnings=[f"{type(exc).__name__}:{exc}"],
                metadata={"error_type": type(exc).__name__},
                completion=(
                    non_success_completion_report(
                        task,
                        execution_status="failed",
                        reason=str(exc),
                        failure_kind=(
                            "worker_output_contract_failure"
                            if output_contract_failure
                            else "parameter_contract_failure"
                            if contract_violation is not None
                            else "worker_execution_failure"
                        ),
                    )
                    if task_contract is not None
                    else {}
                ),
            )

        if not result.output_type:
            result.output_type = task.expected_output_type
        result.metadata.setdefault("task_type", task.task_type)
        result.metadata.setdefault("attempt", task.attempt)
        result.metadata.setdefault("resolved_input_roles", sorted(resolved_inputs))
        result.metadata.setdefault("completion_contract", dict(task.completion_contract or {}))

        if task_contract is not None:
            if not result.completion:
                if str(task_contract.completion_report_source or "runtime") == "runtime":
                    result.completion = runtime_completion_report(
                        task,
                        task_contract,
                        result_status=result.status,
                        output_type=result.output_type,
                        data=result.data,
                        error=result.error,
                    )
                else:
                    result.completion = non_success_completion_report(
                        task,
                        execution_status=(
                            "need_context" if result.status == ResultStatus.NEED_CONTEXT
                            else "blocked" if result.status == ResultStatus.BLOCKED
                            else "failed"
                        ),
                        reason=result.summary or str((result.error or {}).get("message") or "Worker did not complete."),
                        failure_kind=(
                            "context_missing" if result.status == ResultStatus.NEED_CONTEXT
                            else "upstream_worker_failed" if result.status == ResultStatus.BLOCKED
                            else "completion_report_missing"
                        ),
                    )
            try:
                # Program rules validate shape and route flow. They do not infer
                # business completion from summary text, list length, or values.
                self.directory.validate_result(result, task_type=task.task_type)
                if result.completion:
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
            except WorkerContractViolation as exc:
                result = GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.FAILED,
                    output_type=task.expected_output_type,
                    data=None,
                    error={
                        "code": "worker_output_contract_failure",
                        "message": str(exc),
                        "component": task.assigned_agent,
                        "retryable": False,
                    },
                    focus_refs=task.focus_refs,
                    summary=(
                        "Worker 返回结果不符合公开输出合同。"
                        if language != "en"
                        else "The Worker result does not satisfy its public output contract."
                    ),
                    warnings=[str(exc)],
                    metadata={"completion_contract": dict(task.completion_contract or {})},
                    completion=(
                        non_success_completion_report(
                            task,
                            execution_status="failed",
                            reason=str(exc),
                            failure_kind="worker_output_contract_failure",
                        )
                        if task_contract is not None
                        else {}
                    ),
                )

        result.metadata.setdefault("duration_ms", round((time.perf_counter() - started) * 1000, 2))
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
                "payload_schema": result.payload_schema,
                "payload_version": result.payload_version,
                "summary": result.summary[:500],
                "completion_status": str(result.completion.get("completion_status") or ""),
                "expected_task_completed": bool(result.completion.get("expected_task_completed")),
            },
            payload_schema="worker_result_available.v1",
            context_refs=[ref.to_dict() for ref in result.focus_refs[:20]],
            artifact_refs=list(result.artifact_refs[:20]),
            source_refs=[ref.to_dict() for ref in result.evidence_refs[:20]],
            warnings=list(result.warnings[:10]),
            error=dict(result.error or {}),
            metadata={"worker_id": task.worker_id, "task_type": task.task_type},
        )
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
        card = self.directory.get(task.worker_id or task.assigned_agent)
        return run_evidence(
            self.worker_tool_dag_runtime,
            task,
            query,
            output_dir,
            db_path,
            default_top_k,
            worker_prompt=card.private_worker_prompt,
            allowed_tool_names=card.private_tools_for(task.task_type),
        )

    def _run_entity_analysis(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        resolved_inputs: dict[str, Any],
        language: str,
    ) -> GraphWorkerResult:
        return run_entity_analysis(
            self.llm_service,
            task,
            dependency_results,
            resolved_inputs=resolved_inputs,
            language=language,
        )

    def _run_internal_system(
        self,
        task: GraphAgentTask,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
    ) -> GraphWorkerResult:
        return run_internal_system(
            self.worker_tool_executor,
            task,
            output_dir,
            db_path,
            default_top_k,
            provider=self.provider,
        )

    def _run_graph_context(
        self,
        task: GraphAgentTask,
        resolved_inputs: dict[str, Any],
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> GraphWorkerResult:
        return run_graph_context(
            self.worker_tool_executor,
            task,
            output_dir,
            db_path,
            resolved_inputs=resolved_inputs,
        )

    def _run_graph_impact(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        resolved_inputs: dict[str, Any],
    ) -> GraphWorkerResult:
        return run_graph_impact(
            self.impact_service, task, dependency_results, resolved_inputs
        )

    def _run_risk(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        resolved_inputs: dict[str, Any],
        output_dir: str | Path,
        db_path: str | Path | None,
        language: str,
    ) -> GraphWorkerResult:
        card = self.directory.get(task.worker_id or task.assigned_agent)
        return run_risk(
            self.llm_service,
            self.worker_tool_dag_runtime,
            task,
            dependency_results,
            output_dir,
            db_path,
            resolved_inputs=resolved_inputs,
            worker_prompt=card.private_worker_prompt,
            allowed_tool_names=card.private_tools_for(task.task_type),
            language=language,
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
        return run_strategy_guard(
            self.llm_service,
            task,
            current_user_request=current_user_request,
            dependency_results=dependency_results,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            language=language,
            execution_context=execution_context,
        )

    def _run_report_writer(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        resolved_inputs: dict[str, Any],
        language: str,
    ) -> GraphWorkerResult:
        return run_report_writer(
            self.llm_service,
            task,
            dependency_results,
            language,
            resolved_inputs=resolved_inputs,
        )

    def _run_diagnostic(self, task: GraphAgentTask) -> GraphWorkerResult:
        return run_diagnostic(self.provider, task)


__all__ = [
    "SpecialistRuntime",
    "_dependency_results",
    "_refs_from_dependencies",
    "_safe",
]

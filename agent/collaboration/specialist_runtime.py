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

from agent.graph.impact_service import GraphImpactService
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.tool_runtime import ToolExecutor
from agent.worker_tools import WorkerToolDirectory, build_worker_tool_registry

from .agent_directory import (
    AgentDirectory,
    EVIDENCE_RETRIEVER,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from .models import GraphAgentTask, GraphWorkerResult, ResultStatus, TaskStatus
from .worker_contracts import WorkerContractViolation
from .workers import (
    run_diagnostic,
    run_evidence,
    run_graph_impact,
    run_portfolio,
    run_report_writer,
    run_risk,
    run_strategy_guard,
)
from .workers.common import dependency_results as _dependency_results
from .workers.common import refs_from_dependencies as _refs_from_dependencies
from .workers.common import safe_public_value as _safe


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
            if task.metadata.get("structured_worker_contract"):
                self.directory.validate_task_contract(task)
            if task.assigned_agent == EVIDENCE_RETRIEVER:
                result = self._run_evidence(
                    task,
                    current_user_request,
                    output_dir,
                    db_path,
                    default_top_k,
                )
            elif task.assigned_agent == PORTFOLIO_ANALYST:
                result = self._run_portfolio(task, output_dir, db_path)
            elif task.assigned_agent == GRAPH_IMPACT_ANALYST:
                result = self._run_graph_impact(task, dependency_results)
            elif task.assigned_agent == RISK_ANALYST:
                result = self._run_risk(
                    task,
                    dependency_results,
                    output_dir,
                    db_path,
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
                result = self._run_report_writer(
                    task,
                    dependency_results,
                    language,
                )
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
            error_code = (
                "worker_contract_violation"
                if isinstance(exc, WorkerContractViolation)
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
                    "retryable": not isinstance(exc, WorkerContractViolation),
                },
                focus_refs=task.focus_refs,
                summary=(
                    "Worker 输入合同或专业数据链路执行失败。"
                    if language != "en"
                    else "The Worker input contract or specialist data path failed."
                ),
                warnings=[f"{type(exc).__name__}:{exc}"],
                metadata={"error_type": type(exc).__name__},
            )
        if not result.output_type:
            result.output_type = task.expected_output_type
        if task.metadata.get("structured_worker_contract"):
            try:
                self.directory.validate_result(result)
            except WorkerContractViolation as exc:
                result = GraphWorkerResult(
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                    status=ResultStatus.FAILED,
                    output_type=task.expected_output_type,
                    data=None,
                    error={
                        "code": "worker_output_contract_violation",
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
                )
        result.metadata.setdefault("task_type", task.task_type)
        result.metadata.setdefault("attempt", task.attempt)
        result.metadata.setdefault(
            "duration_ms",
            round((time.perf_counter() - started) * 1000, 2),
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
        return run_evidence(
            self.worker_tool_executor,
            task,
            query,
            output_dir,
            db_path,
            default_top_k,
        )

    def _run_portfolio(
        self,
        task: GraphAgentTask,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> GraphWorkerResult:
        return run_portfolio(self.provider, task, output_dir, db_path)

    def _run_graph_impact(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
    ) -> GraphWorkerResult:
        return run_graph_impact(self.impact_service, task, dependency_results)

    def _run_risk(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> GraphWorkerResult:
        return run_risk(
            self.provider,
            task,
            dependency_results,
            output_dir,
            db_path,
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
        language: str,
    ) -> GraphWorkerResult:
        return run_report_writer(
            self.llm_service,
            task,
            dependency_results,
            language,
        )

    def _run_diagnostic(self, task: GraphAgentTask) -> GraphWorkerResult:
        return run_diagnostic(self.provider, task)


__all__ = [
    "SpecialistRuntime",
    "_dependency_results",
    "_refs_from_dependencies",
    "_safe",
]

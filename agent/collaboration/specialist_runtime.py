"""Capability-dispatched runtime for Worker planning and result composition.

The Main Agent assigns a public capability.  This facade verifies the private
Worker binding, lets the Worker plan only capability-authorized private tools,
executes the shared-DAG plan, and returns a GraphWorkerResult.  Domain workers
never receive provider facades directly.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from core.llm import LLMService

from agent.tool_runtime import ToolExecutor
from agent.worker_planning.executor import WorkerPlanExecutor
from agent.worker_planning.planner import WorkerPlanPlanner
from agent.worker_tools import WorkerToolDirectory

from .agent_directory import AgentDirectory
from .models import (
    GraphAgentTask,
    GraphWorkerResult,
    ResultStatus,
    TaskStatus,
    WorkerContextRequest,
)
from .workers import (
    compose_diagnostic_result,
    compose_evidence_result,
    compose_graph_impact_result,
    compose_market_result,
    compose_portfolio_result,
    compose_risk_result,
    compose_strategy_proposal_result,
    provided_evidence_result,
    run_report_composer,
)
from .workers.common import dependency_results as _dependency_results
from .workers.common import refs_from_dependencies as _refs_from_dependencies
from .workers.common import safe_public_value as _safe


ResultComposer = Callable[
    [GraphAgentTask, Any],
    GraphWorkerResult,
]


class SpecialistRuntime:
    """Execute one capability through a registered Worker runtime."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        worker_tool_directory: WorkerToolDirectory,
    ) -> None:
        self.llm_service = llm_service
        self.agent_directory = AgentDirectory()
        self.worker_tool_directory = worker_tool_directory
        self.worker_tool_executor = ToolExecutor(
            registry=worker_tool_directory.registry
        )
        self.worker_planner = WorkerPlanPlanner(
            llm_service=llm_service,
            directory=self.worker_tool_directory,
        )
        self.worker_plan_executor = WorkerPlanExecutor(
            directory=self.worker_tool_directory,
            tool_executor=self.worker_tool_executor,
        )
        self._tool_composers: dict[str, ResultComposer] = {
            "evidence.research": compose_evidence_result,
            "market.stock_analysis": compose_market_result,
            "portfolio.analysis": compose_portfolio_result,
            "graph.impact_analysis": (
                compose_graph_impact_result
            ),
            "portfolio.risk_analysis": compose_risk_result,
            "strategy.proposal": (
                compose_strategy_proposal_result
            ),
            "system.graph_diagnostic": (
                compose_diagnostic_result
            ),
        }
        self._reasoning_handlers = {
            "report.compose": self._run_report_composer,
        }

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
            binding = self.agent_directory.resolve(task.capability_id)
            if binding.worker_id != task.assigned_agent:
                raise RuntimeError(
                    "worker_capability_binding_mismatch"
                )
            if task.capability_id in self._tool_composers:
                result = self._run_tool_capability(
                    task,
                    current_user_request=current_user_request,
                    dependency_results=dependency_results,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    language=language,
                    execution_context=execution_context,
                )
            else:
                handler = self._reasoning_handlers.get(task.capability_id)
                if handler is None:
                    result = GraphWorkerResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                        status=ResultStatus.NOT_EXECUTED,
                        focus_refs=task.focus_refs,
                        summary=(
                            "Unsupported Worker capability: "
                            f"{task.capability_id}"
                        ),
                        warnings=["unknown_worker_capability"],
                    )
                else:
                    result = handler(
                        task,
                        dependency_results,
                        language,
                    )
        except KeyError as exc:
            result = GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NOT_EXECUTED,
                focus_refs=task.focus_refs,
                summary=(
                    "Unsupported Worker capability: "
                    f"{task.capability_id}"
                ),
                warnings=[str(exc.args[0]) if exc.args else str(exc)],
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
                    else (
                        "The financial-graph or specialist data "
                        "path failed."
                    )
                ),
                warnings=[f"{type(exc).__name__}:{exc}"],
                metadata={"error_type": type(exc).__name__},
            )
        if (
            result.status == ResultStatus.NEED_CONTEXT
            and result.context_request is None
            and any(item.blocking for item in result.missing_items)
        ):
            result.context_request = WorkerContextRequest(
                source_task_id=task.task_id,
                source_capability_id=task.capability_id,
                requirements=[
                    item for item in result.missing_items if item.blocking
                ],
                attempt=task.attempt,
            )
        result.metadata.setdefault("task_type", task.task_type)
        result.metadata.setdefault("capability_id", task.capability_id)
        result.metadata.setdefault("attempt", task.attempt)
        result.metadata.setdefault(
            "duration_ms",
            round((time.perf_counter() - started) * 1000, 2),
        )
        task.status = (
            TaskStatus.COMPLETED
            if result.status
            in {
                ResultStatus.COMPLETED,
                ResultStatus.PROPOSAL_READY,
            }
            else TaskStatus.PARTIAL
            if result.status == ResultStatus.PARTIAL
            else TaskStatus.WAITING_CONTEXT
            if result.status == ResultStatus.NEED_CONTEXT
            else TaskStatus.FAILED
        )
        return result

    def _run_tool_capability(
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
        if task.capability_id.startswith("evidence."):
            provided = provided_evidence_result(task)
            if provided is not None:
                return provided
        context = dict(execution_context or {})
        memory_values = {
            **dict(context.get("session_memory_values") or {}),
            **dict(context.get("resolved_context") or {}),
        }
        plan = self.worker_planner.plan(
            task=task,
            user_request=current_user_request,
            dependency_results=dependency_results,
            memory_values=memory_values,
            language=language,
        )
        execution = self.worker_plan_executor.execute(
            plan,
            task=task,
            user_request=current_user_request,
            dependency_results=dependency_results,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            memory_values=memory_values,
            execution_context=context,
        )
        composer = self._tool_composers[task.capability_id]
        result = composer(task, execution)
        result.metadata.setdefault(
            "worker_plan",
            {
                "plan_version": plan.plan_version,
                "step_count": len(plan.steps),
                "execution_basis": "capability_scoped_private_tools",
            },
        )
        return result

    def _run_report_composer(
        self,
        task: GraphAgentTask,
        dependency_results: dict[str, dict[str, Any]],
        language: str,
    ) -> GraphWorkerResult:
        return run_report_composer(
            self.llm_service,
            task,
            dependency_results,
            language,
        )


__all__ = [
    "SpecialistRuntime",
    "_dependency_results",
    "_refs_from_dependencies",
    "_safe",
]

"""LLM planning facade for Main-Agent capability task graphs."""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from .agent_directory import AgentDirectory
from .capability_plan_validator import (
    CapabilityPlanValidator,
    CoordinatorPlanningError,
)
from .models import GraphAgentTask, TaskStatus


class CoordinatorPlanner:
    """Generate a capability DAG without exposing Worker implementation names.

    The LLM selects public ``capability_id`` values. Only after the plan passes
    deterministic validation does the directory bind each capability to an
    internal Worker and task type.
    """

    def __init__(self, directory: AgentDirectory, *, llm_service: LLMService) -> None:
        self.directory = directory
        self.llm_service = llm_service
        self.validator = CapabilityPlanValidator(directory)

    def plan(
        self,
        *,
        query: str,
        request_mode: str,
        session_id: str,
        run_id: str,
        user_id: str,
        focus_refs: list,
        context_refs: list,
        memory_summary: str,
        language: str = "zh",
        as_of_time: str = "",
    ) -> tuple[list[GraphAgentTask], dict[str, Any]]:
        mode = str(request_mode or "analysis").strip().lower()
        try:
            required_plan_outputs = self.directory.required_outputs_for_mode(mode)
        except KeyError as exc:
            raise CoordinatorPlanningError(str(exc.args[0])) from exc

        capability_catalog = self.directory.safe_catalog()

        def validate(payload: dict[str, Any]) -> None:
            self.validator.parse_and_validate(payload, request_mode=mode)

        system = (
            "你是主协调 Agent 的能力规划器。本步骤只生成 Worker 级业务能力任务图。"
            "你只能看到公开的 Worker 能力卡，不能看到、输出或猜测 Worker 名称、Agent 名称、"
            "内部 task_type、私有 Tool、函数、API、Neo4j 标签、Cypher、数据库表、参数 Schema、"
            "provider code、旧 stock_code 字段或旧 intent。"
            "每个任务必须从能力卡中选择一个 capability_id，不得输出 assigned_agent、agent_id、"
            "worker_id、worker_name 或 task_type。"
            "把用户目标拆成 1 到 8 个能力任务。没有依赖的任务可以并行；有依赖的任务必须使用"
            " dependency_task_ids 明确引用上游任务。"
            "某项能力声明的 required_dependency_output_types 必须由它的直接上游任务共同提供。"
            "计划整体必须产生 request_output_policy 中要求的输出类型。"
            "具有 can_finalize=true 的能力应位于任务图末端，并依赖需要纳入最终回答的全部分支。"
            "不要为了填满能力而安排与用户目标无关的任务。"
            "严格输出 JSON："
            "{\"tasks\":[{\"task_id\":\"task_1\",\"capability_id\":\"...\","
            "\"objective\":\"...\",\"constraints\":[],"
            "\"dependency_task_ids\":[],\"required_outputs\":[],\"priority\":1}]}。"
        )
        payload = self.llm_service.generate_json(
            stage="graph_coordinator_planner",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request_mode": mode,
                            "request_output_policy": {
                                "required_output_types": required_plan_outputs
                            },
                            "user_request": str(query or ""),
                            "session_context_summary": str(memory_summary or "")[:6000],
                            "resolved_focus_refs": [
                                ref.to_dict() for ref in focus_refs
                            ],
                            "available_context_refs": [
                                ref.to_dict() for ref in context_refs
                            ],
                            "worker_capability_catalog": capability_catalog,
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=3000,
            validator=validate,
            operation=f"graph_capability_task_plan:{mode}",
        )

        plans = self.validator.parse_and_validate(payload, request_mode=mode)
        tasks: list[GraphAgentTask] = []
        for plan in plans:
            binding = self.directory.resolve(
                plan.capability_id,
                request_mode=mode,
            )
            tasks.append(
                GraphAgentTask(
                    task_id=plan.task_id,
                    run_id=run_id,
                    session_id=session_id,
                    assigned_agent=binding.worker_id,
                    objective=plan.objective,
                    task_type=binding.task_type,
                    user_id=user_id,
                    capability_id=plan.capability_id,
                    focus_refs=list(focus_refs),
                    context_refs=list(context_refs),
                    dependency_task_ids=list(plan.dependency_task_ids),
                    required_outputs=(
                        list(plan.required_outputs)
                        if plan.required_outputs
                        else list(binding.produced_output_types)
                    ),
                    constraints=list(plan.constraints),
                    as_of_time=as_of_time,
                    priority=plan.priority,
                    status=(
                        TaskStatus.READY
                        if not plan.dependency_task_ids
                        else TaskStatus.CREATED
                    ),
                    metadata={
                        "request_mode": mode,
                        "capability_id": plan.capability_id,
                        "produced_output_types": list(
                            binding.produced_output_types
                        ),
                        "side_effect_scope": binding.side_effect_scope,
                        "capability_binding": "runtime_resolved",
                    },
                )
            )
        return tasks, {
            "planner": "coordinator_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "tool_visibility": "none",
            "worker_identity_visibility": "none",
            "selection_basis": "worker_capability",
            "required_plan_outputs": required_plan_outputs,
            "capability_plan_contract_version": "capability_task_plan.v1",
            "graph_contract_version": "graph_agent_task.v1",
        }


__all__ = [
    "CoordinatorPlanner",
    "CoordinatorPlanningError",
]

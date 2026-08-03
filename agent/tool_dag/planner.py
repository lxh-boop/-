"""Shared LLM planner for Worker-private Tool DAGs."""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from agent.console_trace import flow_event
from agent.worker_tools import WorkerToolDirectory

from .contracts import TOOL_DAG_OUTPUT_SCHEMA, ToolDagContractViolation, ToolDagPlan
from .validation import ToolDagValidator

def _safe_planning_value(value: Any, *, depth: int = 0) -> Any:
    """Return a compact, non-secret view used only by the assigned Worker planner."""

    if depth >= 4:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, list):
        return [_safe_planning_value(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, tuple):
        return [_safe_planning_value(item, depth=depth + 1) for item in list(value)[:20]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            name = str(key)
            lowered = name.lower()
            if any(marker in lowered for marker in ("password", "secret", "api_key", "token")):
                result[name] = "<redacted>"
            else:
                result[name] = _safe_planning_value(item, depth=depth + 1)
        return result
    if hasattr(value, "to_dict"):
        try:
            return _safe_planning_value(value.to_dict(), depth=depth + 1)
        except Exception:
            pass
    return str(value)[:500]


class WorkerToolDagPlanner:
    """Plan private Tool nodes without exposing them to MainAgent."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        directory: WorkerToolDirectory,
        validator: ToolDagValidator,
    ) -> None:
        self.llm_service = llm_service
        self.directory = directory
        self.validator = validator

    def plan(
        self,
        *,
        worker_task_id: str,
        worker_role: str,
        worker_objective: str,
        worker_task_type: str,
        worker_prompt: str,
        available_context: dict[str, Any],
        required_output_keys: list[str],
        completion_criteria: list[str],
        allowed_tool_names: list[str],
        run_id: str,
        read_only: bool,
    ) -> ToolDagPlan:
        available_keys = set(available_context)
        allowed = set(allowed_tool_names)
        private_catalog = [
            item
            for item in self.directory.private_catalog(worker_role)
            if str(item.get("tool_id") or "") in allowed
        ]
        fixed_goal_contract = {
            "goal_summary": str(worker_objective),
            "required_output_keys": list(required_output_keys),
            "completion_criteria": list(completion_criteria),
        }

        def validate(payload: dict[str, Any]) -> None:
            candidate = {**dict(payload or {}), "goal_contract": fixed_goal_contract}
            self.validator.validate_payload(
                candidate,
                worker_role=worker_role,
                worker_task_id=worker_task_id,
                available_context_keys=available_keys,
                allowed_tool_names=allowed,
                read_only=read_only,
            )

        def emit(event: str, payload: dict[str, Any]) -> None:
            names = {
                "request_started": "TOOL_DAG_PLANNING_STARTED",
                "response_received": "TOOL_DAG_PLANNING_RESPONSE_RECEIVED",
                "candidate_generated": "TOOL_DAG_CANDIDATE_GENERATED",
                "validation_succeeded": "TOOL_DAG_VALIDATION_SUCCEEDED",
                "validation_failed": "TOOL_DAG_VALIDATION_FAILED",
                "repair_started": "TOOL_DAG_REPAIR_STARTED",
                "repair_response_received": "TOOL_DAG_REPAIR_RESPONSE_RECEIVED",
                "repair_candidate_generated": "TOOL_DAG_REPAIR_CANDIDATE_GENERATED",
                "repair_validation_succeeded": "TOOL_DAG_REPAIR_SUCCEEDED",
                "repair_failed": "TOOL_DAG_REPAIR_FAILED",
            }
            flow_event(
                names.get(event, f"TOOL_DAG_{event.upper()}"),
                payload,
                run_id=run_id,
                task_id=worker_task_id,
                level="ERROR" if "failed" in event else "INFO",
            )

        system = (
            "你是某一个专业 Worker 内部的 Tool DAG Planner。MainAgent 已经给出高层 Worker 任务；"
            "你只能从 private_tool_catalog 选择该 Worker 私有工具，不能选择其他 Worker、不能修改 Worker DAG、"
            "不能输出不存在的工具。根据当前任务目标和 available_context_keys 动态生成最小 Tool DAG。"
            "允许单节点 DAG，也允许多个无依赖工具并行。不要因为工具可能有帮助就全部选择；只选择完成目标需要的工具。"
            "args 只放普通常量。权威运行时值必须通过 inputs 中的 {\"from_context\":\"key\"} 引用。"
            "工具间传递只允许 {\"from_tool_task_id\":\"TT1\"}；只有确实需要上游 data 某字段时才增加 data_key。"
            "一个参数需要多个上游结果时，直接使用上述引用对象组成的数组；禁止创造 from_task、from_task_ids、output_key 等别名。"
            "同一个参数只能存在于 args 或 inputs 一处。final_output_task_ids 必须指向真正完成 Worker 目标的末端任务。"
            "所有任务必须位于 final_output_task_ids 的依赖闭包中，不能生成无用节点。Validator 只接受或拒绝，不会替你补任务。"
            "不要输出 goal_contract，也不要输出 expected_output_keys；目标合同和工具必需输出字段均由程序根据注册 Schema 编译。"
            "严格输出 tool_dag_output_schema 对应 JSON，不要 Markdown。"
        )
        payload = self.llm_service.generate_json(
            stage="worker_tool_dag_planner",
            messages=[
                {"role": "system", "content": system + "\nWorker private boundary:\n" + str(worker_prompt or "")},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "worker_task_id": worker_task_id,
                            "worker_role": worker_role,
                            "worker_task_type": worker_task_type,
                            "worker_objective": worker_objective,
                            "available_context_keys": sorted(available_keys),
                            "available_context": _safe_planning_value(available_context),
                            "fixed_goal_contract": fixed_goal_contract,
                            "private_tool_catalog": private_catalog,
                            "tool_dag_output_schema": TOOL_DAG_OUTPUT_SCHEMA,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=4200,
            validator=validate,
            operation=f"worker_tool_dag_plan:{worker_role}:{worker_task_type}",
            event_callback=emit,
            repair_mode="targeted",
            repair_guidance=(
                "只修复校验指出的 Tool、参数引用、依赖、最终输出或无用节点。"
                "不要增加未注册工具，不要修改 Worker 目标，不要把 context 值直接编造进 args。"
                "保持最小 DAG；单节点合法。"
            ),
        )
        return self.validator.validate_payload(
            {**dict(payload or {}), "goal_contract": fixed_goal_contract},
            worker_role=worker_role,
            worker_task_id=worker_task_id,
            available_context_keys=available_keys,
            allowed_tool_names=allowed,
            read_only=read_only,
        )

    def replan(
        self,
        *,
        previous_plan: ToolDagPlan,
        node_records: list[dict[str, Any]],
        reusable_results: dict[str, Any],
        available_context: dict[str, Any],
        worker_prompt: str,
        allowed_tool_names: list[str],
        run_id: str,
        read_only: bool,
    ) -> ToolDagPlan:
        reusable_ids = set(reusable_results)
        frozen_rows = [
            task.planning_dict()
            for task in previous_plan.tasks
            if task.tool_task_id in reusable_ids
        ]
        frozen_signatures = {
            task.tool_task_id: task.to_dict()
            for task in previous_plan.tasks
            if task.tool_task_id in reusable_ids
        }
        previous_ids = {task.tool_task_id for task in previous_plan.tasks}
        available_keys = set(available_context)
        allowed = set(allowed_tool_names)
        private_catalog = [
            item
            for item in self.directory.private_catalog(previous_plan.worker_role)
            if str(item.get("tool_id") or "") in allowed
        ]

        def validate(payload: dict[str, Any]) -> None:
            candidate = {**dict(payload or {}), "goal_contract": dict(previous_plan.goal_contract or {})}
            self.validator.validate_payload(
                candidate,
                worker_role=previous_plan.worker_role,
                worker_task_id=previous_plan.worker_task_id,
                available_context_keys=available_keys,
                allowed_tool_names=allowed,
                read_only=read_only,
                frozen_task_signatures=frozen_signatures,
                previous_task_ids=previous_ids,
            )

        def emit(event: str, payload: dict[str, Any]) -> None:
            flow_event(
                f"TOOL_DAG_REPLAN_{event.upper()}",
                payload,
                run_id=run_id,
                task_id=previous_plan.worker_task_id,
                level="ERROR" if "failed" in event else "INFO",
            )

        payload = self.llm_service.generate_json(
            stage="worker_tool_dag_replanner",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你负责 Worker 内部 Tool DAG 的局部重规划。node_execution_records 对所有成功、失败、阻塞节点使用同一结构；"
                        "should_freeze=true 的节点状态不可改写。frozen_reusable_tasks 是其中可通过 result_ref 复用的成功节点，必须完全保留且不得重新执行。"
                        "失败或阻塞节点不要保留为可执行旧节点，只新增补齐剩余目标所需的最小替代子图。不得修改 Worker 目标。"
                        "工具间输入只允许 {from_tool_task_id, 可选data_key}，上下文只允许 {from_context}；禁止 from_task/from_task_ids/output_key 等别名。"
                        "同一参数不得同时放入 args 和 inputs。新 tool_task_id 不得复用 previous_task_ids。"
                        "不要输出 goal_contract 或 expected_output_keys；它们由程序从固定目标和 Tool Schema 编译。允许单节点或并行节点。严格输出 JSON。\n"
                        + str(worker_prompt or "")
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "fixed_goal_contract": previous_plan.goal_contract,
                            "available_context_keys": sorted(available_keys),
                            "available_context": _safe_planning_value(available_context),
                            "frozen_reusable_tasks": frozen_rows,
                            "reusable_result_summaries": {
                                task_id: next(
                                    (
                                        dict(item.get("result_summary") or {})
                                        for item in node_records
                                        if str(item.get("tool_task_id") or "") == task_id
                                    ),
                                    {
                                        "data_keys": sorted((getattr(result, "data", {}) or {}).keys()),
                                    },
                                )
                                for task_id, result in reusable_results.items()
                            },
                            "node_execution_records": node_records,
                            "previous_task_ids": sorted(previous_ids),
                            "private_tool_catalog": private_catalog,
                            "tool_dag_output_schema": TOOL_DAG_OUTPUT_SCHEMA,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            max_output_tokens=4200,
            validator=validate,
            operation=f"worker_tool_dag_replan:{previous_plan.worker_role}",
            event_callback=emit,
            repair_mode="targeted",
            repair_guidance=(
                "保持 frozen_reusable_tasks；只修复工具引用、依赖和最终输出。目标合同由程序固定注入。"
                "inputs 只能使用 from_context 或 from_tool_task_id(+可选data_key)；多个上游使用引用数组。"
                "不要把同一字段同时放入 args 和 inputs。新节点必须使用新的 tool_task_id。"
            ),
        )
        return self.validator.validate_payload(
            {**dict(payload or {}), "goal_contract": dict(previous_plan.goal_contract or {})},
            worker_role=previous_plan.worker_role,
            worker_task_id=previous_plan.worker_task_id,
            available_context_keys=available_keys,
            allowed_tool_names=allowed,
            read_only=read_only,
            frozen_task_signatures=frozen_signatures,
            previous_task_ids=previous_ids,
        )


__all__ = ["WorkerToolDagPlanner"]

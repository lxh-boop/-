"""Progressive LLM planner for Worker-private Tool DAGs.

A Worker first receives summaries for compatible private Tools. After selecting
candidate Tool IDs, only those Tools expose full descriptions and schemas for
DAG planning. MainAgent never sees either layer.
"""

from __future__ import annotations

from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import catalog_for_prompt, compact_json_dumps, schema_for_prompt

from agent.console_trace import flow_event
from agent.worker_tools import WorkerToolDirectory

from .contracts import TOOL_DAG_OUTPUT_SCHEMA, ToolDagContractViolation, ToolDagPlan
from .validation import ToolDagValidator


def _safe_planning_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, (list, tuple)):
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

    def _select_tool_candidates(
        self,
        *,
        worker_task_id: str,
        worker_role: str,
        worker_objective: str,
        boundary_id: str,
        available_tool_names: set[str],
        required_output_keys: list[str],
        available_context_keys: set[str],
        run_id: str,
        replan_context: dict[str, Any] | None = None,
    ) -> list[str]:
        summaries = self.directory.summary_catalog(
            worker_role,
            tool_names=sorted(available_tool_names),
        )
        flow_event(
            "TOOL_SUMMARY_CATALOG_LOADED",
            {
                "worker_role": worker_role,
                "compatible_tool_count": len(summaries),
                "tool_ids": [item["tool_id"] for item in summaries],
                "visibility": "summary_only",
            },
            run_id=run_id,
            task_id=worker_task_id,
        )
        if not summaries:
            raise ToolDagContractViolation(
                "no_compatible_private_tool",
                "$.private_tool_summary_catalog",
                ",".join(sorted(available_context_keys)),
            )
        if len(summaries) == 1:
            selected = [str(summaries[0]["tool_id"])]
            flow_event(
                "TOOL_CANDIDATE_SELECTION_COMPLETED",
                {
                    "candidate_tool_ids": selected,
                    "selection_mode": "single_compatible_tool",
                },
                run_id=run_id,
                task_id=worker_task_id,
            )
            return selected

        known = {str(item.get("tool_id") or "") for item in summaries}
        required = {str(item) for item in required_output_keys if str(item)}

        def validate(payload: dict[str, Any]) -> None:
            ids = payload.get("candidate_tool_ids")
            if not isinstance(ids, list) or not ids:
                raise ToolDagContractViolation("tool_candidate_list_required", "$.candidate_tool_ids")
            normalized = [str(item or "").strip() for item in ids]
            if len(normalized) != len(set(normalized)):
                raise ToolDagContractViolation("duplicate_tool_candidate", "$.candidate_tool_ids")
            unknown = sorted(set(normalized) - known)
            if unknown:
                raise ToolDagContractViolation(
                    "unknown_tool_candidate",
                    "$.candidate_tool_ids",
                    ",".join(unknown),
                )
            selected_rows = [item for item in summaries if item["tool_id"] in normalized]
            covered = {
                str(slot)
                for item in selected_rows
                for slot in item.get("produced_output_slots") or []
                if str(slot)
            }
            if required and not required.issubset(covered):
                missing = sorted(required - covered)
                raise ToolDagContractViolation(
                    "tool_candidates_do_not_cover_worker_outputs",
                    "$.candidate_tool_ids",
                    ",".join(missing),
                )

            # Candidate Tools must form a reachable capability chain from the
            # Worker's current context. A downstream Tool may depend on a slot
            # produced by another selected private Tool; Runtime validates the
            # chain but never chooses the sequence on the Worker's behalf.
            available_slots = set(available_context_keys)
            pending = {str(item.get("tool_id") or ""): item for item in selected_rows}
            while pending:
                progressed = False
                for tool_id, item in list(pending.items()):
                    required_slots = {
                        str(slot)
                        for slot in item.get("required_input_slots") or []
                        if str(slot)
                    }
                    if required_slots.issubset(available_slots):
                        available_slots.update(
                            str(slot)
                            for slot in item.get("produced_output_slots") or []
                            if str(slot)
                        )
                        pending.pop(tool_id, None)
                        progressed = True
                if not progressed:
                    raise ToolDagContractViolation(
                        "tool_candidates_missing_reachable_prerequisite_chain",
                        "$.candidate_tool_ids",
                        ",".join(sorted(pending)),
                    )

        user_payload: dict[str, Any] = {
            "worker_task_id": worker_task_id,
            "worker_role": worker_role,
            "boundary_id": boundary_id,
            "worker_objective": worker_objective,
            "available_context_keys": sorted(available_context_keys),
            "required_output_keys": list(required_output_keys),
            "private_tool_summary_catalog": summaries,
            "required_output_shape": {
                "candidate_tool_ids": ["tool.id"],
                "selection_reason": "short reason",
            },
        }
        if replan_context:
            user_payload["local_replan_context"] = replan_context
        payload = self.llm_service.generate_json(
            stage="worker_tool_candidate_selection",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是专业Worker的私有Tool候选选择阶段。当前只看到从现有上下文或其他私有Tool产出可达的Tool摘要。"
                        "选择完成Worker合同所需的最小候选Tool集合；如果目标Tool的输入需要由另一个私有Tool先产生，必须把该前置Tool一并选入候选集合。"
                        "不得选择摘要之外的Tool，不生成DAG，不生成参数。只输出JSON。"
                    ),
                },
                {"role": "user", "content": compact_json_dumps(user_payload)},
            ],
            max_output_tokens=600,
            validator=validate,
            operation=f"select_private_tool_candidates:{worker_role}:{boundary_id}",
            disable_thinking=True,
            repair_mode="targeted",
            repair_guidance="只修复候选Tool ID、重复项或输出覆盖问题。",
        )
        selected = list(dict.fromkeys(
            str(item or "").strip()
            for item in payload.get("candidate_tool_ids") or []
            if str(item or "").strip()
        ))
        flow_event(
            "TOOL_CANDIDATE_SELECTION_COMPLETED",
            {
                "candidate_tool_ids": selected,
                "selection_mode": "summary_then_details",
                "selection_reason": str(payload.get("selection_reason") or "")[:1000],
            },
            run_id=run_id,
            task_id=worker_task_id,
        )
        return selected

    def plan(
        self,
        *,
        worker_task_id: str,
        worker_role: str,
        worker_objective: str,
        boundary_id: str,
        worker_prompt: str,
        available_context: dict[str, Any],
        required_output_keys: list[str],
        completion_criteria: list[str],
        allowed_tool_names: list[str],
        run_id: str,
        read_only: bool,
    ) -> ToolDagPlan:
        available_keys = set(available_context)
        requested_allowed = set(allowed_tool_names)
        compatible = set(self.directory.reachable_tool_names(
            worker_role,
            available_context_keys=available_keys,
            allowed_tool_names=requested_allowed,
        ))
        selected = self._select_tool_candidates(
            worker_task_id=worker_task_id,
            worker_role=worker_role,
            worker_objective=worker_objective,
            boundary_id=boundary_id,
            available_tool_names=compatible,
            required_output_keys=required_output_keys,
            available_context_keys=available_keys,
            run_id=run_id,
        )
        allowed = set(selected)
        private_catalog = catalog_for_prompt(self.directory.load_details(worker_role, selected))
        flow_event(
            "TOOL_DETAILS_LOADED",
            {
                "worker_role": worker_role,
                "loaded_tool_ids": selected,
                "tool_detail_count": len(private_catalog),
                "main_agent_visibility": "none",
            },
            run_id=run_id,
            task_id=worker_task_id,
        )
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
            "你是专业Worker内部的Tool DAG Planner。你先看过兼容Tool摘要，现在只获得已选候选Tool的完整描述和Schema。"
            "只能从 private_tool_details_catalog 选择Tool；不得选择其他Worker或修改Worker DAG。"
            "根据任务目标和available_context生成最小Tool DAG。允许后续Tool消费前序Tool产生的语义Output Slot；由你决定Tool顺序和依赖。args只放普通常量，权威值通过inputs的from_context或from_tool_task_id引用。"
            "当输入来自前序Tool时，优先使用{from_tool_task_id, output_slot}，output_slot必须来自上游Tool的output_contract；不要猜测records/items等Python内部data_key。"
            "工具间只允许from_tool_task_id引用。final_output_task_ids必须指向完成目标的末端任务。"
            "不要输出goal_contract或expected_output_keys。严格输出JSON。"
        )
        payload = self.llm_service.generate_json(
            stage="worker_private_tool_dag_planner",
            messages=[
                {"role": "system", "content": system + "\nWorker private boundary:\n" + str(worker_prompt or "")},
                {
                    "role": "user",
                    "content": compact_json_dumps({
                        "worker_task_id": worker_task_id,
                        "worker_role": worker_role,
                        "boundary_id": boundary_id,
                        "worker_objective": worker_objective,
                        "available_context_keys": sorted(available_keys),
                        "available_context": _safe_planning_value(available_context),
                        "fixed_goal_contract": fixed_goal_contract,
                        "private_tool_details_catalog": private_catalog,
                        "tool_dag_output_schema": schema_for_prompt(TOOL_DAG_OUTPUT_SCHEMA),
                    }),
                },
            ],
            max_output_tokens=2000,
            validator=validate,
            operation=f"worker_private_tool_dag_plan:{worker_role}:{boundary_id}",
            disable_thinking=True,
            event_callback=emit,
            repair_mode="targeted",
            repair_guidance=(
                "只修复Tool、参数引用、依赖、最终输出或无用节点。不得增加未加载Tool。保持最小DAG。"
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

        # Deterministic completion gate before any local-Replan LLM call.  A
        # successful Tool set is authoritative when its frozen node records
        # already cover every Worker-required output key.  This is generic: it
        # depends only on the Tool DAG goal contract and node output records,
        # never on Worker IDs or business-specific Tool names.
        required_output_keys = {
            str(item) for item in previous_plan.goal_contract.get("required_output_keys") or []
            if str(item)
        }
        frozen_output_keys = {
            str(key)
            for record in node_records
            if str(record.get("status") or "") == "succeeded"
            and bool(record.get("execution_success", True))
            and bool(record.get("contract_valid", True))
            and bool(record.get("should_freeze", True))
            for key in record.get("produced_output_keys") or []
            if str(key)
        }
        if required_output_keys and required_output_keys.issubset(frozen_output_keys):
            flow_event(
                "TOOL_DAG_REPLAN_SKIPPED",
                {
                    "reason": "required_outputs_already_satisfied",
                    "required_output_keys": sorted(required_output_keys),
                    "frozen_output_keys": sorted(frozen_output_keys),
                    "reusable_tool_task_ids": sorted(reusable_ids),
                },
                run_id=run_id,
                task_id=previous_plan.worker_task_id,
            )
            return previous_plan

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
        requested_allowed = set(allowed_tool_names)
        compatible = set(self.directory.reachable_tool_names(
            previous_plan.worker_role,
            available_context_keys=available_keys,
            allowed_tool_names=requested_allowed,
        ))
        frozen_tool_names = {
            str(task.tool_name)
            for task in previous_plan.tasks
            if task.tool_task_id in reusable_ids
        }
        candidate_pool = compatible.union(frozen_tool_names)
        selected = self._select_tool_candidates(
            worker_task_id=previous_plan.worker_task_id,
            worker_role=previous_plan.worker_role,
            worker_objective=str(previous_plan.goal_contract.get("goal_summary") or ""),
            boundary_id="local_replan",
            available_tool_names=candidate_pool,
            required_output_keys=list(previous_plan.goal_contract.get("required_output_keys") or []),
            available_context_keys=available_keys,
            run_id=run_id,
            replan_context={
                "node_execution_records": node_records,
                "frozen_tool_ids": sorted(frozen_tool_names),
            },
        )
        allowed = set(selected).union(frozen_tool_names)
        private_catalog = catalog_for_prompt(
            self.directory.load_details(previous_plan.worker_role, sorted(allowed))
        )
        flow_event(
            "TOOL_DETAILS_LOADED",
            {
                "worker_role": previous_plan.worker_role,
                "loaded_tool_ids": sorted(allowed),
                "tool_detail_count": len(private_catalog),
                "replan": True,
            },
            run_id=run_id,
            task_id=previous_plan.worker_task_id,
        )

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
            stage="progressive_worker_tool_dag_replanner",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你负责Worker内部Tool DAG局部重规划。保留frozen_reusable_tasks，只新增完成剩余目标的最小替代子图。"
                        "新节点可以通过{from_tool_task_id, output_slot}直接消费frozen_reusable_tasks的语义Output Slot，不要重复执行已冻结成功节点，也不要引用其Python内部data_key。"
                        "只能使用已加载Tool详情，不修改Worker目标。若现有冻结结果已经满足目标，不应进入本阶段。"
                        "严格输出JSON。\n" + str(worker_prompt or "")
                    ),
                },
                {
                    "role": "user",
                    "content": compact_json_dumps({
                        "fixed_goal_contract": previous_plan.goal_contract,
                        "available_context_keys": sorted(available_keys),
                        "available_context": _safe_planning_value(available_context),
                        "frozen_reusable_tasks": frozen_rows,
                        "node_execution_records": node_records,
                        "previous_task_ids": sorted(previous_ids),
                        "private_tool_details_catalog": private_catalog,
                        "tool_dag_output_schema": schema_for_prompt(TOOL_DAG_OUTPUT_SCHEMA),
                    }),
                },
            ],
            max_output_tokens=2400,
            validator=validate,
            operation=f"progressive_worker_tool_dag_replan:{previous_plan.worker_role}",
            disable_thinking=True,
            event_callback=emit,
            repair_mode="targeted",
            repair_guidance="保留冻结结果，只修复未完成部分；跨Tool传递使用output_slot，不得猜测data_key；不得返回空DAG或使用未加载Tool。",
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

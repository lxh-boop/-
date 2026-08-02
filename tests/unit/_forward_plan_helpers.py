from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.collaboration.agent_directory import AgentDirectory


_FAILURE_POLICY = {
    "missing_parameter": "repair_args_or_request_user",
    "missing_context": "pause_and_request_context",
    "tool_failure": "retry_or_select_equivalent_capability",
    "business_empty": "accept_valid_empty_and_report_limit",
    "business_insufficient": "forward_replan_from_current_state",
}


def decorate_forward_plan(
    plan: dict[str, Any],
    *,
    initial_slots: list[str],
    goal_slots: list[str] | None = None,
) -> dict[str, Any]:
    """Add V11 GoalContract/TaskExpectation fields to a compact test plan."""

    result = deepcopy(plan)
    directory = AgentDirectory()
    rows = result["tasks"]
    by_id = {str(row["task_id"]): row for row in rows}
    outputs_by_id: dict[str, list[str]] = {}

    for row in rows:
        card = directory.get(str(row["worker_id"]))
        contract = card.task_contract(str(row["task_type"]))
        produced = list(contract.produces_information_slots)
        outputs_by_id[str(row["task_id"])] = produced
        runtime_args = sorted(contract.authoritative_arg_bindings)
        direct_args = sorted(
            (set(row.get("args") or {}) | set(contract.default_args))
            - set(runtime_args)
        )
        refs = [
            item
            for value in (row.get("inputs") or {}).values()
            for item in (value if isinstance(value, list) else [value])
            if isinstance(item, dict)
        ]
        dependency_ids = [str(item["from_task_id"]) for item in refs]
        upstream_slots = sorted(
            {
                slot
                for dependency_id in dependency_ids
                for slot in outputs_by_id.get(dependency_id, [])
            }
        )
        context_slots = [
            slot
            for slot in contract.required_context_slots
            if slot in set(initial_slots)
        ]
        row.update(
            {
                "purpose": str(row.get("objective") or "完成本次业务子目标"),
                "why_selected": "当前输入可满足该能力，并对全局目标有直接或下游贡献。",
                "input_contract": {
                    "direct_arg_names": direct_args,
                    "runtime_bound_args": runtime_args,
                    "upstream_information_slots": upstream_slots,
                    "available_context_slots": context_slots,
                },
                "expected_output": {
                    "output_type": str(row["expected_output_type"]),
                    "information_slots": produced,
                    "coverage_requirement": str(
                        contract.coverage_semantics.get("scope") or "task_declared_scope"
                    ),
                    "freshness_requirement": str(
                        contract.freshness_semantics.get("policy") or "preserve_upstream_time"
                    ),
                    "authority_requirement": str(
                        contract.authority_level or "declared_capability_authority"
                    ),
                },
                "expected_effect": {
                    "goal_slots_satisfied": [],
                    "unlocks_information_slots": produced,
                    "used_by_task_ids": [],
                },
                "completion_criteria": list(contract.completion_criteria),
                "failure_policy": dict(_FAILURE_POLICY),
                "replan_triggers": [
                    "输出类型正确但必需信息槽位未覆盖",
                    "结果覆盖范围低于本次任务要求",
                    "数据新鲜度或权威来源不符合预期",
                ],
            }
        )

    # Fill downstream use after every producer is known.
    for row in rows:
        for value in (row.get("inputs") or {}).values():
            refs = value if isinstance(value, list) else [value]
            for item in refs:
                if not isinstance(item, dict):
                    continue
                source = by_id.get(str(item.get("from_task_id") or ""))
                if source is None:
                    continue
                source["expected_effect"]["used_by_task_ids"].append(
                    str(row["task_id"])
                )

    if goal_slots is None:
        goal_slots = []
        for row in rows:
            if row["expected_output_type"] == "FinalReport":
                goal_slots.extend(row["expected_output"]["information_slots"])
            elif not row["expected_effect"]["used_by_task_ids"]:
                goal_slots.extend(row["expected_output"]["information_slots"])
        if not goal_slots:
            goal_slots = ["user_facing_report"]
    goal_slots = list(dict.fromkeys(goal_slots))
    result["goal_contract"]["required_information_slots"] = goal_slots
    for row in rows:
        produced = set(row["expected_output"]["information_slots"])
        row["expected_effect"]["goal_slots_satisfied"] = sorted(
            produced.intersection(goal_slots)
        )
        row["expected_effect"]["used_by_task_ids"] = list(
            dict.fromkeys(row["expected_effect"]["used_by_task_ids"])
        )

    final_slots = list(initial_slots)
    for row in rows:
        final_slots.extend(row["expected_output"]["information_slots"])
    result["planning_state"] = {
        "initial_available_information_slots": list(initial_slots),
        "final_planned_information_slots": list(dict.fromkeys(final_slots)),
        "unmet_information_slots": [],
        "stop_reason": "全部目标信息槽位已有生产者，停止正向扩展。",
    }
    return result

"""Run-local read-only Proposal Worker.

W05 is an LLM Worker that transforms authoritative upstream WorkerResults into a
structured ReviewedProposal. Producing advice or a proposal is READ: no proposal
row, order, portfolio, strategy, profile, or other persistent business state is
written here. Persisting or executing a proposal belongs to the separate WRITE
confirmation protocol.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm import LLMService

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..worker_contracts import (
    array_schema,
    object_schema,
    string_schema,
    validate_schema,
)
from .common import execution_safe_value, materialize_promised_slots, safe_public_value
from .slot_inputs import slot_envelopes
from .structured_output import generate_json_with_local_structural_repair


def _proposal_output_schema() -> dict[str, Any]:
    return object_schema(
        {
            "action": string_schema(enum=["proposal_ready", "need_context", "blocked"]),
            "proposal": {"type": "object", "additionalProperties": True},
            "source_task_ids": array_schema(string_schema(min_length=1)),
            "limitations": array_schema({"type": "string"}),
            "reason": {"type": "string"},
            "missing_items": array_schema(
                object_schema(
                    {
                        "key": string_schema(min_length=1),
                        "description": string_schema(min_length=1),
                        "expected_format": {"type": "string"},
                    },
                    required=["key", "description", "expected_format"],
                    additional_properties=False,
                )
            ),
            "requires_approval": {"type": "boolean"},
            "execution_allowed": {"type": "boolean"},
        },
        required=[
            "action",
            "proposal",
            "source_task_ids",
            "limitations",
            "reason",
            "missing_items",
            "requires_approval",
            "execution_allowed",
        ],
        additional_properties=False,
    )


def _collect_hard_constraint_breaches(value: Any) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key in ("hard_constraint_breaches", "single_position_limit_breaches"):
                rows = item.get(key)
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        security_ref = str(row.get("security_ref") or "").strip()
                        if security_ref:
                            found[security_ref] = dict(row)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(
        found.values(),
        key=lambda item: float(item.get("current_asset_weight") or 0.0),
        reverse=True,
    )


def run_strategy_guard(
    llm_service: LLMService,
    task: GraphAgentTask,
    *,
    current_user_request: str,
    resolved_inputs: dict[str, Any] | None,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    language: str,
    execution_context: dict[str, Any] | None,
) -> GraphWorkerResult:
    # These parameters remain in the stable Worker facade but are intentionally
    # unused: a READ proposal must not invoke a persistent proposal tool.
    del output_dir, db_path, default_top_k, execution_context

    input_envelopes = [
        row for row in slot_envelopes(task, resolved_inputs, projection="execution")
        if row.get("source_task_ids")
    ]
    safe_dependencies = execution_safe_value(input_envelopes)
    hard_constraint_breaches = _collect_hard_constraint_breaches(resolved_inputs or {})
    allowed_source_ids = {
        str(source_id)
        for row in input_envelopes
        for source_id in row.get("source_task_ids") or []
        if str(source_id)
    }

    def validate(payload: dict[str, Any]) -> None:
        validate_schema(payload, _proposal_output_schema())
        action = str(payload.get("action") or "")
        source_ids = [str(item) for item in payload.get("source_task_ids") or []]
        unknown = sorted(set(source_ids) - allowed_source_ids)
        if unknown:
            raise RuntimeError("proposal_unknown_source_task_ids:" + ",".join(unknown))
        if action == "proposal_ready":
            if not bool(payload.get("requires_approval")):
                raise RuntimeError("proposal_requires_approval_must_be_true")
            if bool(payload.get("execution_allowed")):
                raise RuntimeError("proposal_execution_allowed_must_be_false")
            if not isinstance(payload.get("proposal"), dict) or not payload.get("proposal"):
                raise RuntimeError("proposal_payload_required")
            if hard_constraint_breaches:
                responses = payload["proposal"].get("constraint_response")
                if not isinstance(responses, list):
                    raise RuntimeError("proposal_constraint_response_required")
                by_security = {
                    str(item.get("security_ref") or ""): item
                    for item in responses if isinstance(item, dict) and str(item.get("security_ref") or "")
                }
                for breach in hard_constraint_breaches:
                    security_ref = str(breach.get("security_ref") or "")
                    response = by_security.get(security_ref)
                    if not response:
                        raise RuntimeError("proposal_constraint_response_missing:" + security_ref)
                    if str(response.get("action") or "") != "reduce_to_limit":
                        raise RuntimeError("proposal_constraint_action_invalid:" + security_ref)
                    try:
                        target = float(response.get("target_asset_weight"))
                        limit = float(breach.get("max_allowed_asset_weight"))
                    except (TypeError, ValueError):
                        raise RuntimeError("proposal_constraint_target_invalid:" + security_ref)
                    if target > limit + 1e-12 or target < 0:
                        raise RuntimeError("proposal_constraint_target_exceeds_limit:" + security_ref)

    generation_messages = [
            {
                "role": "system",
                "content": (
                    "你是 W05 Strategy Guard，是只读的 LLM Worker。你的任务是把用户明确的变更目标和"
                    "上游合同绑定的结构化信息Slot转换为当前 Run 内的 ReviewedProposal，或明确返回 need_context/blocked。"
                    "分析、建议和待审批 Proposal 都属于 READ；不得调用写工具，不得保存 Proposal，不得修改账户、"
                    "持仓、策略、画像或配置，不得声称已经执行。只使用 structured_upstream_results 中的事实，"
                    "不得补造证券、持仓、风险、模型信号或约束。proposal_ready 时 requires_approval 必须为 true，"
                    "execution_allowed 必须为 false。若 hard_constraint_breaches 非空，这些是确定性的用户硬约束违例："
                    "proposal 必须包含 constraint_response 数组，逐一覆盖每个 security_ref；每项 action 必须为 reduce_to_limit，"
                    "target_asset_weight 不得高于 max_allowed_asset_weight。行业数据缺失可以限制新增配置，但不能成为忽略已有硬约束违例的理由。"
                    "涉及集中度时必须标明 total_assets 或 position_market_value 分母，不得混用 asset_weight 与 invested_weight。"
                    "Runtime负责完成度和合同验收。规则只校验结构和引用，业务方案由你依据结构化输入完成。"
                    "严格输出 proposal_output_schema 对应的 JSON，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": str(current_user_request or ""),
                        "task": task.safe_for_coordinator(),
                        "worker_args": safe_public_value(task.args),
                        "structured_input_slots": safe_dependencies,
                        "hard_constraint_breaches": safe_public_value(hard_constraint_breaches),
                        "constraint_response_contract": {
                            "required_when_breaches_exist": True,
                            "required_fields": ["security_ref", "action", "target_asset_weight"],
                            "required_action": "reduce_to_limit",
                            "target_rule": "target_asset_weight <= max_allowed_asset_weight",
                        },
                        "allowed_source_task_ids": sorted(allowed_source_ids),
                        "proposal_persistence_policy": {
                            "access_mode": "read",
                            "scope": "current_run_only",
                            "persistent_write_performed": False,
                            "execution_allowed": False,
                        },
                        "reply_language": "en" if language == "en" else "zh",
                        "proposal_output_schema": _proposal_output_schema(),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
    payload = generate_json_with_local_structural_repair(
        llm_service,
        stage="graph_strategy_guard",
        operation=task.boundary_id,
        messages=generation_messages,
        output_schema=_proposal_output_schema(),
        validator=validate,
        immutable_repair_context={
            "allowed_source_task_ids": sorted(allowed_source_ids),
            "hard_constraint_breaches": safe_public_value(hard_constraint_breaches),
            "requires_approval": True,
            "execution_allowed": False,
        },
        repair_guidance=(
            "Repair JSON shape, source_task_ids, approval flags, and constraint_response using only immutable hard_constraint_breaches. "
            "Every breached security_ref must have action=reduce_to_limit and target_asset_weight <= max_allowed_asset_weight. "
            "Do not add other upstream facts and do not turn the proposal into a write operation."
        ),
        primary_max_output_tokens=3200,
        repair_max_output_tokens=1800,
        primary_disable_thinking=False,
    )

    action = str(payload.get("action") or "")
    if action == "need_context":
        missing = [
            MissingContextItem(
                key=str(item.get("key") or "proposal_context"),
                description=str(item.get("description") or "生成方案所需上下文"),
                expected_format=str(item.get("expected_format") or "结构化业务参数"),
                reason=str(payload.get("reason") or "当前上游信息不足。"),
                searched_sources=["task", "RunSlotStore", "resolved_input_bindings"],
            )
            for item in payload.get("missing_items") or []
            if isinstance(item, dict)
        ]
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="ReviewedProposal",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary=str(payload.get("reason") or "生成方案前需要补充信息。"),
            missing_items=missing,
            limitations=[str(item) for item in payload.get("limitations") or []],
        )
    if action == "blocked":
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.BLOCKED,
            output_type="ReviewedProposal",
            data=None,
            error={
                "code": "proposal_blocked",
                "message": str(payload.get("reason") or "当前输入不能形成安全的待审批方案。"),
                "component": "strategy_guard",
                "retryable": False,
            },
            focus_refs=task.focus_refs,
            summary=str(payload.get("reason") or "当前输入不能形成安全的待审批方案。"),
            warnings=[str(item) for item in payload.get("limitations") or []],
        )

    proposal_id = f"run:{task.run_id}:proposal:{task.task_id}"
    proposal = safe_public_value(payload.get("proposal") or {})
    proposal_slot = {
        "proposal_id": proposal_id,
        "plan_id": "",
        "proposal": proposal,
        "source_task_ids": [str(item) for item in payload.get("source_task_ids") or []],
        "limitations": [str(item) for item in payload.get("limitations") or []],
        "requires_approval": True,
        "execution_allowed": False,
        "access_mode": "read",
        "scope": "current_run_only",
        "persistent_write_performed": False,
    }
    slots = materialize_promised_slots(task, proposal_slot)
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.PROPOSAL_READY,
        output_type="ReviewedProposal",
        data={**proposal_slot, "slots": slots},
        error=None,
        focus_refs=task.focus_refs,
        summary=str(payload.get("reason") or "已生成当前 Run 内的待审批方案，尚未保存或执行。"),
        findings=[
            {
                "kind": "run_local_proposal",
                "proposal_id": proposal_id,
                "source_task_ids": [str(item) for item in payload.get("source_task_ids") or []],
            }
        ],
        confidence=0.9,
        warnings=[str(item) for item in payload.get("limitations") or []],
        metadata={
            "proposal_id": proposal_id,
            "requires_approval": True,
            "execution_allowed": False,
            "access_mode": "read",
            "persistent_write_performed": False,
        },
    )

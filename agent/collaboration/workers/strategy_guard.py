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

from ..completion import validate_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from ..worker_contracts import (
    array_schema,
    completion_report_schema,
    object_schema,
    string_schema,
    validate_schema,
)
from .common import dependency_results as dependency_result_items
from .common import safe_public_value


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
            "completion_report": completion_report_schema(),
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
            "completion_report",
        ],
        additional_properties=False,
    )


def run_strategy_guard(
    llm_service: LLMService,
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
    # These parameters remain in the stable Worker facade but are intentionally
    # unused: a READ proposal must not invoke the legacy persistent proposal tool.
    del output_dir, db_path, default_top_k, execution_context

    selected_ids = list(dict.fromkeys(task.dependency_task_ids or dependency_results.keys()))
    selected = {
        task_id: payload
        for task_id, payload in dependency_results.items()
        if not selected_ids or task_id in set(selected_ids)
    }
    safe_dependencies = safe_public_value(dependency_result_items(selected))
    allowed_source_ids = set(selected)

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
        validate_completion_report(
            dict(payload.get("completion_report") or {}),
            dict(task.completion_contract or {}),
            path="$.completion_report",
        )

    payload = llm_service.generate_json(
        stage="graph_strategy_guard",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 W05 Strategy Guard，是只读的 LLM Worker。你的任务是把用户明确的变更目标和"
                    "上游权威 WorkerResult 转换为当前 Run 内的 ReviewedProposal，或明确返回 need_context/blocked。"
                    "分析、建议和待审批 Proposal 都属于 READ；不得调用写工具，不得保存 Proposal，不得修改账户、"
                    "持仓、策略、画像或配置，不得声称已经执行。只使用 structured_upstream_results 中的事实，"
                    "不得补造证券、持仓、风险、模型信号或约束。proposal_ready 时 requires_approval 必须为 true，"
                    "execution_allowed 必须为 false。逐项对照 completion_contract 返回 completion_report，"
                    "report_source 必须为 llm。规则只校验结构和引用，业务方案由你依据结构化输入完成。"
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
                        "structured_upstream_results": safe_dependencies,
                        "allowed_source_task_ids": sorted(allowed_source_ids),
                        "completion_contract": dict(task.completion_contract or {}),
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
        ],
        max_output_tokens=3200,
        validator=validate,
        operation=task.task_type,
        repair_mode="targeted",
        disable_thinking=False,
        repair_guidance=(
            "只修复 JSON Schema、source_task_ids、requires_approval/execution_allowed 和 completion_report。"
            "不得新增上游没有的业务事实，不得转成写操作。"
        ),
    )

    action = str(payload.get("action") or "")
    completion = dict(payload.get("completion_report") or {})
    if action == "need_context":
        missing = [
            MissingContextItem(
                key=str(item.get("key") or "proposal_context"),
                description=str(item.get("description") or "生成方案所需上下文"),
                expected_format=str(item.get("expected_format") or "结构化业务参数"),
                reason=str(payload.get("reason") or "当前上游信息不足。"),
                searched_sources=["task", "structured_upstream_results", "session_context"],
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
            completion=completion,
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
            completion=completion,
        )

    proposal_id = f"run:{task.run_id}:proposal:{task.task_id}"
    proposal = safe_public_value(payload.get("proposal") or {})
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.PROPOSAL_READY,
        output_type="ReviewedProposal",
        data={
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
        },
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
        completion=completion,
    )

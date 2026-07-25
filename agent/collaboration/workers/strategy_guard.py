"""Execute the proposal-only Strategy Guard Worker.

The Worker selects one allowed proposal capability using the run-scoped LLM and
may create a pending approval artifact. It never grants approval, commits a
strategy, activates a binding, or changes current positions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm import LLMService

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import dependency_results as dependency_result_items
from .common import safe_public_value


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
    from agent.tool_engine import (
        AGENT_MAIN,
        OP_PROPOSAL,
        execute_tool_legacy_dict,
        get_tool_registry_v2,
    )

    registry = get_tool_registry_v2()
    catalog: list[dict[str, Any]] = []
    for definition in registry.list(agent_type=AGENT_MAIN, operation_type=OP_PROPOSAL):
        if str(getattr(definition, "operation_type", "")).lower() != str(OP_PROPOSAL).lower():
            continue
        catalog.append(
            {
                "name": str(definition.name),
                "description": str(definition.description),
                "input_schema": dict(definition.input_schema or {}),
                "produced_outputs": list(definition.produced_outputs or []),
                "requires_approval": bool(definition.requires_approval),
            }
        )
    if not catalog:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            focus_refs=task.focus_refs,
            summary="没有可用的 Proposal 能力，未进行任何写入。",
            warnings=["proposal_capability_catalog_empty"],
        )
    allowed = {item["name"] for item in catalog}

    def validate(payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "").lower()
        if action not in {"execute_proposal", "need_context", "blocked"}:
            raise RuntimeError("invalid_strategy_guard_action")
        if action == "execute_proposal" and str(payload.get("capability") or "") not in allowed:
            raise RuntimeError("proposal_capability_not_allowed")

    decision = llm_service.generate_json(
        stage="graph_strategy_guard",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 Strategy Guard 的私有 Proposal 规划器。主 Agent 看不到这些私有能力。"
                    "只能选择一个 proposal 能力生成待审批预案，禁止 Commit，禁止表示已经执行。"
                    "Agent 公共实体引用均为 GraphRef，不得要求主 Agent 提供 stock_code。"
                    "严格输出 JSON：{\"action\":\"execute_proposal|need_context|blocked\","
                    "\"capability\":\"\",\"parameters\":{},\"reason\":\"\",\"missing_items\":[]}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": task.safe_for_coordinator(),
                        "user_request": current_user_request,
                        "dependency_results": safe_public_value(
                            dependency_result_items(dependency_results)
                        ),
                        "available_proposal_capabilities": catalog,
                        "reply_language": language,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        max_output_tokens=2200,
        validator=validate,
        operation=task.task_type,
    )
    action = str(decision.get("action") or "").lower()
    if action == "need_context":
        missing = [
            MissingContextItem(
                key=str(item.get("key") or "proposal_context"),
                description=str(item.get("description") or "生成预案所需上下文"),
                expected_format=str(item.get("expected_format") or "明确目标或数值"),
                reason=str(decision.get("reason") or "无法安全生成 Proposal。"),
                searched_sources=[
                    "task",
                    "dependency_results",
                    "private_proposal_planner",
                ],
            )
            for item in decision.get("missing_items") or []
            if isinstance(item, dict)
        ]
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="生成预案前需要补充信息。",
            missing_items=missing,
        )
    if action == "blocked":
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.BLOCKED,
            focus_refs=task.focus_refs,
            summary=str(decision.get("reason") or "当前请求不能安全形成预案。"),
        )

    params = dict(decision.get("parameters") or {})
    params.pop("account_id", None)
    params["user_id"] = task.user_id
    raw = execute_tool_legacy_dict(
        str(decision.get("capability") or ""),
        params,
        context={
            **dict(execution_context or {}),
            "output_dir": output_dir,
            "db_path": db_path,
            "default_top_k": default_top_k,
            "user_id": task.user_id,
            "session_id": task.session_id,
            "conversation_id": task.session_id,
            "run_id": task.run_id,
            "task_id": task.task_id,
            "agent_role": task.assigned_agent,
            "dependency_results": dependency_results,
            "graph_refs": [
                ref.to_dict() for ref in task.focus_refs + task.context_refs
            ],
            "llm_runtime_settings": llm_service.settings,
            "llm_profile_id": llm_service.profile_id,
            "llm_config_hash": llm_service.config_hash,
        },
        agent_type=AGENT_MAIN,
        approval_granted=False,
    )
    success = bool(raw.get("success"))
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    plan_id = str(data.get("plan_id") or raw.get("plan_id") or "")
    proposal_id = str(data.get("proposal_id") or raw.get("proposal_id") or "")
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.PROPOSAL_READY if success else ResultStatus.FAILED,
        focus_refs=task.focus_refs,
        summary=str(raw.get("message") or ("已生成待审批预案。" if success else "预案生成失败。")),
        findings=[
            {
                "kind": "proposal",
                "plan_id": plan_id,
                "proposal_id": proposal_id,
                "data": safe_public_value(data),
            }
        ],
        confidence=1.0 if success else 0.0,
        warnings=[str(item) for item in raw.get("warnings") or []],
        metadata={
            "plan_id": plan_id,
            "proposal_id": proposal_id,
            "requires_approval": success,
        },
    )

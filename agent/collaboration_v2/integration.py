from __future__ import annotations

from pathlib import Path
from typing import Any

from core.llm import LLMService

from .control_gateway import ControlGateway
from .contracts import STANDARDIZED_RESULTS_CONTRACT_VERSION
from .coordinator import AgentCollaborationCoordinator
from .entry_decision import EntryDecision, RequestMode
from .llm_runtime import require_run_llm_service
from .session_memory import SessionMemoryStore


class UnifiedAgentRequest:
    """Compatibility object that always names the one Main Coordinator entry."""

    def __init__(self, query: str) -> None:
        self.intent = "agent_collaboration_v2"
        self.parameters: dict[str, Any] = {}
        self.execution_route = "single_main_agent_entry"
        self.decomposition: dict[str, Any] = {
            "query": str(query or ""),
            "route_layer": "single_main_agent_entry",
            "tasks": [],
            "is_multi_intent": False,
            "need_clarification": False,
            "clarification_question": "",
            "unsupported_reason": "",
            "confidence": 1.0,
            "warnings": [],
            "user_goal": {
                "raw_message": str(query or ""),
                "resolved_message": str(query or ""),
                "action": "main_agent_decides",
                "objects": [],
                "constraints": [],
                "expected_outputs": ["standardized_agent_results_or_control_result"],
            },
            "task_plan": {
                "tasks": [],
                "planning_level": "agent",
                "tool_visibility": "none",
                "old_router_used": False,
            },
            "supervisor_decision": {
                "decision_source": "single_main_agent_entry",
                "intent": "agent_collaboration_v2",
                "tasks": [],
                "agent_sequence": [],
                "dependencies": {},
                "requires_write": False,
                "confidence": 1.0,
                "reason": "all_requests_enter_main_coordinator",
                "safety_flags": [
                    "coordinator_tool_visibility_none",
                    "legacy_router_disabled",
                    "single_entry_only",
                ],
            },
            "diagnostics": {
                "llm_used": False,
                "decision_source": "single_main_agent_entry",
                "llm_planner_called": False,
                "fallback_used": False,
                "legacy_router_called": False,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "parameters": dict(self.parameters),
            "query": str(self.decomposition.get("query") or ""),
            "decomposition": dict(self.decomposition),
            "execution_route": self.execution_route,
        }


def route_unified_agent_request(query: str, **_: Any) -> UnifiedAgentRequest:
    """Non-semantic compatibility façade; semantic planning occurs once later."""
    return UnifiedAgentRequest(str(query or ""))


def execute_unified_agent_request(
    *,
    query: str,
    user_id: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    default_top_k: int = 50,
    session_id: str = "",
    run_id: str = "",
    language: str = "zh",
    llm_service: LLMService | None = None,
    context: dict[str, Any] | None = None,
    decomposition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = require_run_llm_service(llm_service=llm_service, run_id=run_id)
    coordinator = AgentCollaborationCoordinator(
        output_dir=output_dir,
        db_path=db_path,
        llm_service=binding.service,
    )
    result = coordinator.execute(
        query=str(query or ""),
        decomposition=dict(decomposition or {}),
        user_id=str(user_id or "default"),
        default_top_k=max(1, min(int(default_top_k or 50), 100)),
        session_id=str(session_id or f"session_{user_id}"),
        run_id=str(run_id or ""),
        language=str(language or "zh"),
        execution_context=dict(context or {}),
    )
    result.setdefault(
        "standardized_agent_results",
        {
            "contract_version": STANDARDIZED_RESULTS_CONTRACT_VERSION,
            "items": [],
            "task_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "waiting_context_count": 0,
        },
    )
    collab = result.setdefault("agent_collaboration_v2", {})
    collab["llm_binding"] = binding.public_dict()
    collab["llm_binding"]["single_service_identity"] = True
    return result


def execute_control_action(
    *,
    action: str,
    query: str = "",
    plan_id: str = "",
    confirmation_token: str = "",
    user_id: str = "default",
    session_id: str = "",
    run_id: str = "",
    language: str = "zh",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit UI-card control path inside the same ControlGateway boundary."""
    normalized = str(action or "").strip().lower()
    mode = {
        "confirm": RequestMode.CONFIRM,
        "reject": RequestMode.REJECT,
        "language": RequestMode.LANGUAGE,
    }.get(normalized)
    if mode is None:
        raise ValueError(f"unsupported_control_action:{normalized}")
    merged_context = dict(context or {})
    if plan_id:
        merged_context["plan_id"] = plan_id
    if confirmation_token:
        merged_context["confirmation_token"] = confirmation_token
    decision = EntryDecision(
        mode=mode,
        reply_language=language if mode == RequestMode.LANGUAGE else "",
        reason="explicit_ui_control_action",
        source="hard_control_gateway",
        confidence=1.0,
    )
    return ControlGateway(output_dir=output_dir, db_path=db_path).execute(
        decision=decision,
        query=query,
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
        language=language,
        execution_context=merged_context,
    )


# Compatibility names all delegate to the exact same implementation.
def execute_agent_collaboration_v2(**kwargs: Any) -> dict[str, Any]:
    return execute_unified_agent_request(**kwargs)


def route_agent_query_v2_compat(*args: Any, **kwargs: Any) -> UnifiedAgentRequest:
    query = ""
    if args:
        query = str(args[1] if callable(args[0]) and len(args) > 1 else args[0])
    else:
        query = str(kwargs.get("query") or "")
    return route_unified_agent_request(query)


def should_use_agent_collaboration_v2(intent: str, decomposition: dict[str, Any] | None = None) -> bool:
    del decomposition
    return str(intent or "") == "agent_collaboration_v2"


def clear_agent_collaboration_session(
    session_id: str,
    *,
    output_dir: str | Path = "outputs",
    hard: bool = True,
) -> dict[str, int]:
    return SessionMemoryStore(output_dir=output_dir).clear_session(session_id, hard=hard)

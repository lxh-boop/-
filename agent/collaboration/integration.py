from __future__ import annotations

from pathlib import Path
from typing import Any

from core.llm import LLMService

from .control_gateway import ControlGateway
from .coordinator import AgentCollaborationCoordinator
from .entry_decision import EntryDecision, RequestMode
from .llm_runtime import require_run_llm_service
from .session_memory import SessionMemoryStore


class UnifiedGraphAgentRequest:
    """The sole public Agent entry after the Neo4j hard cut."""

    def __init__(self, query: str) -> None:
        self.intent = "financial_graph_agent"
        self.parameters: dict[str, Any] = {}
        self.execution_route = "single_main_agent_graph_entry"
        self.decomposition = {
            "query": str(query or ""),
            "route_layer": "single_main_agent_graph_entry",
            "tasks": [],
            "is_multi_intent": False,
            "need_clarification": False,
            "clarification_question": "",
            "confidence": 1.0,
            "warnings": [],
            "user_goal": {
                "raw_message": str(query or ""),
                "resolved_message": str(query or ""),
                "action": "main_agent_decides",
                "objects": [],
                "constraints": [],
                "expected_outputs": ["graph_worker_results_or_control_result"],
            },
            "task_plan": {
                "tasks": [],
                "planning_level": "worker_agent",
                "tool_visibility": "none",
                "legacy_entity_protocol": False,
            },
            "supervisor_decision": {
                "decision_source": "single_main_agent_graph_entry",
                "intent": "financial_graph_agent",
                "tasks": [],
                "agent_sequence": [],
                "dependencies": {},
                "requires_write": False,
                "confidence": 1.0,
                "reason": "all_requests_enter_existing_main_coordinator_with_graph_contracts",
                "safety_flags": [
                    "coordinator_tool_visibility_none",
                    "worker_private_tools",
                    "neo4j_entity_authority",
                    "legacy_public_entity_protocol_disabled",
                ],
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


def route_unified_agent_request(query: str, **_: Any) -> UnifiedGraphAgentRequest:
    return UnifiedGraphAgentRequest(str(query or ""))


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
    try:
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
    finally:
        coordinator.close()
    runtime = result.setdefault("graph_runtime", {})
    runtime["llm_binding"] = binding.public_dict()
    runtime["llm_binding"]["single_service_identity"] = True
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


def should_use_financial_graph_agent(intent: str, decomposition: dict[str, Any] | None = None) -> bool:
    del decomposition
    return str(intent or "") == "financial_graph_agent"


def clear_financial_graph_agent_session(
    session_id: str,
    *,
    output_dir: str | Path = "outputs",
    hard: bool = True,
) -> dict[str, int]:
    return SessionMemoryStore(output_dir=output_dir).clear_session(session_id, hard=hard)

from __future__ import annotations

from typing import Any

from agent.context.context_types import ContextBundle


def build_planner_context(
    bundle: ContextBundle,
    *,
    turn_context: dict[str, Any] | None = None,
    target_portfolio_refs: list[dict[str, Any]] | None = None,
    strategy_context: dict[str, Any] | None = None,
    default_top_k: int | None = None,
) -> dict[str, Any]:
    """Create the only context object sent to the planning LLM."""

    turn = dict(turn_context or {})
    relation = str(
        ((turn.get("turn_resolution") or {}).get("relation_type"))
        or ((turn.get("conversation_state") or {}).get("relation_type"))
        or bundle.conversation_context.metadata.get("relation_type")
        or ""
    )
    is_follow_up = bool((turn.get("follow_up") or {}).get("is_follow_up"))
    memory = bundle.memory_context
    return {
        "context_id": bundle.context_id,
        "user_id": bundle.user_id,
        "conversation_id": bundle.conversation_id,
        "run_id": bundle.run_id,
        "current_message": str(turn.get("current_message") or ""),
        "resolved_message": str(turn.get("resolved_message") or ""),
        "turn_resolution": {
            "relation_type": relation,
            "confidence": (turn.get("turn_resolution") or {}).get("confidence"),
            "reference_turn_ids": list(
                (turn.get("turn_resolution") or {}).get("reference_turn_ids")
                or []
            )[:8],
        },
        "follow_up": dict(turn.get("follow_up") or {}),
        "previous_user_goal": (
            dict(turn.get("previous_user_goal") or {}) if is_follow_up else {}
        ),
        "previous_result_summary": (
            str(turn.get("previous_result_summary") or "")[:1200]
            if is_follow_up
            else ""
        ),
        "pending_clarification": dict(turn.get("pending_clarification") or {}),
        "explicit_parameters": dict(turn.get("explicit_parameters") or {}),
        "inherited_parameters": (
            dict(turn.get("inherited_parameters") or {}) if is_follow_up else {}
        ),
        "active_entities": dict(turn.get("active_entities") or {}),
        "memory_context": {
            "retrieval_id": memory.retrieval_id,
            "memory_refs": list(memory.memory_refs),
            "items": list(memory.items),
            "diagnostics": {
                "candidate_count": memory.candidate_count,
                "threshold_pass_count": memory.threshold_pass_count,
                "selected_count": memory.selected_count,
                "relevance_threshold": memory.relevance_threshold,
                "token_budget": memory.token_budget,
                "token_used": memory.token_used,
            },
        },
        "approval": {
            "pending_plan_id": bundle.approval_context.pending_plan_id,
            "plan_hash": bundle.approval_context.plan_hash,
            "status": bundle.approval_context.status,
            "token_present": bundle.approval_context.token_present,
        },
        "artifact_refs": list(bundle.artifact_context.artifact_refs)[:12],
        "target_portfolio_refs": list(target_portfolio_refs or [])[:8],
        "strategy_context": _compact_strategy_context(strategy_context or {}),
        "default_top_k": default_top_k,
    }


def _compact_strategy_context(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "strategy_id",
        "strategy_name",
        "strategy_version",
        "proposal_id",
        "status",
        "summary",
        "change_summary",
        "constraints",
        "pending_questions",
        "implementation_requested",
    }
    return {
        str(key): item
        for key, item in value.items()
        if str(key) in allowed
    }


__all__ = ["build_planner_context"]

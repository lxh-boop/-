from __future__ import annotations

from typing import Any

from core.llm import LLMService

from agent.console_trace import flow_event, trace_event
from agent.intent_decomposition.prompts import (
    build_completion_messages,
    build_critic_messages,
    build_messages,
    build_report_messages,
    build_review_messages,
)
from agent.intent_decomposition.schemas import CompletionAssessment, IntentDecomposition


class IntentDecompositionError(RuntimeError):
    """Raised when an LLM-first response cannot be safely validated."""


_SENSITIVE_KEYS = {
    "api_key", "llm_api_key", "password", "secret", "authorization", "cookie",
    "db_path", "database_path", "local_path", "internal_file_path", "output_dir",
    "confirmation_token", "confirmation_token_hash", "raw_payload", "raw_tool_payload",
    "raw_positions", "raw_evidence", "stack", "stack_trace", "traceback",
    "private_chain_of_thought", "chain_of_thought", "reasoning_content",
}


def _safe_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.lower() in _SENSITIVE_KEYS:
                continue
            result[name] = _safe_payload(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_payload(item, depth=depth + 1) for item in list(value)[:30]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 2400:
            return value[:2400] + "...<truncated>"
        return value
    text = str(value)
    return text[:2400] + ("...<truncated>" if len(text) > 2400 else "")


def _validate_planner(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("user_goal"), dict):
        raise IntentDecompositionError("planner_missing_user_goal")
    if not isinstance(payload.get("task_plan"), dict):
        raise IntentDecompositionError("planner_missing_task_plan")


def _validate_review(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("goal_review"), dict):
        raise IntentDecompositionError("review_missing_goal_review")
    if not isinstance(payload.get("plan_review"), dict):
        raise IntentDecompositionError("review_missing_plan_review")


def decompose_with_llm(
    query: str,
    *,
    llm_service: LLMService,
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    rule_hints: dict[str, Any] | None = None,
) -> IntentDecomposition:
    """Generate UserGoal/TaskPlan and review them with one bound service."""

    safe_context = _safe_payload(context or {})
    safe_hints = _safe_payload(rule_hints or {})
    trace_event("planner.llm.start", {"query": query, "context": safe_context, "rule_hints": safe_hints})
    candidate = llm_service.generate_json(
        stage="planner",
        messages=build_messages(
            query,
            reply_language=reply_language,
            context=safe_context,
            rule_hints=safe_hints,
        ),
        max_output_tokens=3000,
        operation="intent_decomposition",
        validator=_validate_planner,
    )

    trace_event("planner.llm.candidate", candidate)
    flow_event(
        "LLM_USER_GOAL",
        {
            "query": query,
            "user_goal": candidate.get("user_goal") or {},
            "planner_confidence": candidate.get("confidence"),
            "need_clarification": candidate.get("need_clarification", False),
            "clarification_question": candidate.get("clarification_question", ""),
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    flow_event(
        "TASK_PLAN",
        {
            "task_plan": candidate.get("task_plan") or {},
            "task_count": len(((candidate.get("task_plan") or {}).get("tasks") or [])),
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    review = llm_service.generate_json(
        stage="goal_reviewer",
        messages=build_review_messages(
            query=query,
            candidate=_safe_payload(candidate),
            reply_language=reply_language,
            context=safe_context,
            rule_hints=safe_hints,
        ),
        max_output_tokens=2400,
        operation="goal_and_plan_review",
        validator=_validate_review,
    )

    trace_event("planner.llm.review", review)
    flow_event(
        "GOAL_REVIEW",
        {
            "goal_review": review.get("goal_review") or {},
            "need_clarification": review.get("need_clarification", False),
            "clarification_question": review.get("clarification_question", ""),
            "review_confidence": review.get("confidence"),
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    flow_event(
        "PLAN_REVIEW",
        {"plan_review": review.get("plan_review") or {}, "warnings": review.get("warnings") or []},
        run_id=str((context or {}).get("run_id") or ""),
    )
    merged = dict(candidate)
    merged["goal_review"] = dict(review.get("goal_review") or {})
    merged["plan_review"] = dict(review.get("plan_review") or {})
    for key in ("need_clarification", "clarification_question", "unsupported_reason"):
        if review.get(key) not in (None, "", False):
            merged[key] = review.get(key)
    merged["warnings"] = [*list(candidate.get("warnings") or []), *list(review.get("warnings") or [])]
    if review.get("confidence") not in (None, ""):
        try:
            merged["confidence"] = min(float(candidate.get("confidence", 0.0)), float(review["confidence"]))
        except (TypeError, ValueError):
            pass

    decomposition = IntentDecomposition.from_dict(
        merged,
        query=query,
        route_layer="llm_first",
        diagnostics={
            "llm_used": True,
            "llm_goal_parser_called": True,
            "llm_goal_plan_reviewer_called": True,
            "model": llm_service.profile.model_name,
            "llm_mode": llm_service.profile.deployment_mode,
            "llm_provider": llm_service.profile.provider_id,
            "llm_profile_id": llm_service.profile_id,
            "llm_config_hash": llm_service.config_hash,
            "business_rule_fallback_disabled": True,
        },
    )
    trace_event("planner.llm.complete", decomposition.to_dict())
    return decomposition


def assess_completion_with_llm(
    user_goal: dict[str, Any],
    produced: dict[str, Any],
    *,
    llm_service: LLMService,
    context: dict[str, Any] | None = None,
) -> CompletionAssessment:
    parsed = llm_service.generate_json(
        stage="completion",
        messages=build_completion_messages(
            user_goal=_safe_payload(user_goal),
            produced=_safe_payload(produced),
            context=_safe_payload(context or {}),
        ),
        max_output_tokens=1300,
        operation="completion_assessment",
    )
    return CompletionAssessment.from_dict(parsed, llm_used=True)


def generate_report_with_llm(
    *,
    query: str,
    user_goal: dict[str, Any],
    result_summary: dict[str, Any],
    completion: dict[str, Any],
    draft_answer: str,
    reply_language: str,
    llm_service: LLMService,
    context: dict[str, Any] | None = None,
) -> str:
    trace_event("report.llm.start", {"query": query, "user_goal": user_goal, "completion": completion})
    parsed = llm_service.generate_json(
        stage="report",
        messages=build_report_messages(
            query=query,
            user_goal=_safe_payload(user_goal),
            result_summary=_safe_payload(result_summary),
            completion=_safe_payload(completion),
            draft_answer=str(draft_answer or "")[:6000],
            reply_language=reply_language,
            context=_safe_payload(context or {}),
        ),
        max_output_tokens=2000,
        operation="report_generation",
    )
    answer = str(parsed.get("answer") or "").strip()
    if not answer:
        raise IntentDecompositionError("LLM report returned an empty answer.")
    trace_event("report.llm.complete", {"answer": answer})
    flow_event(
        "REPORT",
        {"report_mode": str((user_goal or {}).get("action") or ""), "user_goal": user_goal, "completion": completion, "answer": answer},
        run_id=str((context or {}).get("run_id") or ""),
    )
    return answer


def critique_report_with_llm(
    *,
    query: str,
    user_goal: dict[str, Any],
    completion: dict[str, Any],
    answer: str,
    result_summary: dict[str, Any],
    reply_language: str,
    llm_service: LLMService,
) -> dict[str, Any]:
    trace_event("semantic_critic.llm.start", {"query": query, "user_goal": user_goal, "completion": completion, "answer": answer})
    parsed = llm_service.generate_json(
        stage="critic",
        messages=build_critic_messages(
            query=query,
            user_goal=_safe_payload(user_goal),
            completion=_safe_payload(completion),
            answer=str(answer or "")[:7000],
            result_summary=_safe_payload(result_summary),
            reply_language=reply_language,
        ),
        max_output_tokens=1800,
        operation="semantic_critic",
    )
    action = str(parsed.get("action") or "pass").strip().lower()
    if action not in {"pass", "revise", "ask_user", "block"}:
        action = "block"
    result = {
        "action": action,
        "issues": [str(item) for item in (parsed.get("issues") or []) if str(item).strip()][:20],
        "revised_answer": str(parsed.get("revised_answer") or "").strip(),
        "clarification_question": str(parsed.get("clarification_question") or "").strip(),
        "block_message": str(parsed.get("block_message") or "").strip(),
        "confidence": parsed.get("confidence", 0.0),
        "llm_used": True,
    }
    trace_event("semantic_critic.llm.complete", result)
    flow_event("CRITIC", {"critic_type": "llm_semantic_critic", "result": result, "user_goal": user_goal, "completion": completion})
    return result


__all__ = [
    "IntentDecompositionError",
    "assess_completion_with_llm",
    "critique_report_with_llm",
    "decompose_with_llm",
    "generate_report_with_llm",
]

from __future__ import annotations

import json
from typing import Any, Callable

from llm_client import LLMClient
from core.llm.runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings

from agent.console_trace import flow_event, trace_event, trace_exception
from agent.llm_audit import record_schema_result

from agent.intent_decomposition.prompts import (
    build_completion_messages,
    build_critic_messages,
    build_messages,
    build_report_messages,
    build_review_messages,
)
from agent.intent_decomposition.schemas import CompletionAssessment, IntentDecomposition


class IntentDecompositionError(RuntimeError):
    """Raised when an LLM-first planning response cannot be safely parsed."""


_SENSITIVE_KEYS = {
    "api_key", "llm_api_key", "password", "secret", "authorization", "cookie",
    "db_path", "database_path", "local_path", "internal_file_path", "output_dir",
    "confirmation_token", "confirmation_token_hash", "raw_payload", "raw_tool_payload",
    "raw_positions", "raw_evidence", "stack", "stack_trace", "traceback",
    "private_chain_of_thought", "chain_of_thought", "reasoning_content",
}


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise IntentDecompositionError("LLM returned empty JSON output.")
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start < 0:
        raise IntentDecompositionError("No JSON object found in LLM output.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise IntentDecompositionError(f"Invalid JSON returned by LLM: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise IntentDecompositionError("LLM output is not a JSON object.")
                return parsed
    raise IntentDecompositionError("Incomplete JSON object returned by LLM.")


def _client(*, api_key: str | None, base_url: str | None, model: str | None, llm_settings: LLMRuntimeSettings | None = None) -> LLMClient:
    client = LLMClient(settings=llm_settings) if llm_settings is not None else LLMClient(api_key=api_key, base_url=base_url, model=model)
    if client.mode == "api" and not client.api_key:
        raise IntentDecompositionError("Remote API key is not configured; no local fallback was attempted.")
    return client


def _safe_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
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
        return [_safe_payload(item, depth=depth + 1) for item in list(value)[:80]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 5000:
            return value[:5000] + "...<truncated>"
        return value
    text = str(value)
    return text[:5000] + ("...<truncated>" if len(text) > 5000 else "")


def _chat_json(
    client: LLMClient,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    stage: str,
    operation: str = "",
    validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Call once and make one schema-repair attempt. Never use a rule fallback."""
    if hasattr(client, "chat_audited"):
        output = client.chat_audited(
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
            audit_stage=stage,
            audit_operation=operation or "primary",
        )
    else:  # Compatibility for explicit unit-test doubles only.
        output = client.chat(messages=messages, temperature=0.0, max_tokens=max_tokens)
    try:
        parsed = _extract_json_object(output)
        if validator:
            validator(parsed)
        record_schema_result(getattr(client, "last_audit_event_id", ""), True)
        return parsed
    except Exception as first_exc:
        record_schema_result(getattr(client, "last_audit_event_id", ""), False)
        trace_exception("llm.json.first_parse_failed", first_exc)
        repair_messages = [
            *messages,
            {"role": "assistant", "content": str(output or "")[:6000]},
            {
                "role": "user",
                "content": (
                    "上一个输出不是符合要求的 JSON。请保持原任务不变，"
                    "严格按照系统给出的 schema 重新输出一个 JSON 对象。"
                    "不要 Markdown，不要解释，不要猜测缺失信息；不确定时必须请求澄清。"
                ),
            },
        ]
        if hasattr(client, "chat_audited"):
            repaired = client.chat_audited(
                messages=repair_messages,
                temperature=0.0,
                max_tokens=max_tokens,
                audit_stage=stage,
                audit_operation="schema_repair",
            )
        else:  # Compatibility for explicit unit-test doubles only.
            repaired = client.chat(messages=repair_messages, temperature=0.0, max_tokens=max_tokens)
        try:
            parsed = _extract_json_object(repaired)
            if validator:
                validator(parsed)
            record_schema_result(getattr(client, "last_audit_event_id", ""), True)
            trace_event("llm.json.repair_succeeded", {"keys": sorted(parsed.keys())})
            return parsed
        except Exception as second_exc:
            record_schema_result(getattr(client, "last_audit_event_id", ""), False)
            trace_exception("llm.json.repair_failed", second_exc)
            raise IntentDecompositionError(
                f"LLM JSON/schema repair failed: {type(first_exc).__name__}; {type(second_exc).__name__}: {second_exc}"
            ) from second_exc


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
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    rule_hints: dict[str, Any] | None = None,
) -> IntentDecomposition:
    """Generate UserGoal/TaskPlan and review them in two independent LLM calls."""
    client = _client(api_key=api_key, base_url=base_url, model=model, llm_settings=llm_settings)
    safe_context = _safe_payload(context or {})
    safe_hints = _safe_payload(rule_hints or {})

    trace_event("planner.llm.start", {"query": query, "context": safe_context, "rule_hints": safe_hints})
    candidate = _chat_json(
        client,
        build_messages(
            query,
            reply_language=reply_language,
            context=safe_context,
            rule_hints=safe_hints,
        ),
        max_tokens=3000,
        stage="planner",
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
    review = _chat_json(
        client,
        build_review_messages(
            query=query,
            candidate=_safe_payload(candidate),
            reply_language=reply_language,
            context=safe_context,
            rule_hints=safe_hints,
        ),
        max_tokens=2400,
        stage="goal_reviewer",
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
        {
            "plan_review": review.get("plan_review") or {},
            "warnings": review.get("warnings") or [],
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    merged = dict(candidate)
    merged["goal_review"] = dict(review.get("goal_review") or {})
    merged["plan_review"] = dict(review.get("plan_review") or {})
    for key in ("need_clarification", "clarification_question", "unsupported_reason"):
        if review.get(key) not in (None, "", False):
            merged[key] = review.get(key)
    merged["warnings"] = [
        *list(candidate.get("warnings") or []),
        *list(review.get("warnings") or []),
    ]
    review_confidence = review.get("confidence")
    if review_confidence not in (None, ""):
        try:
            merged["confidence"] = min(float(candidate.get("confidence", 0.0)), float(review_confidence))
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
            "model": str(client.model or ""),
            "llm_mode": client.mode,
            "llm_provider": client.provider,
            "llm_config_hash": client.settings.config_hash,
            "business_rule_fallback_disabled": True,
        },
    )
    trace_event("planner.llm.complete", decomposition.to_dict())
    return decomposition


def assess_completion_with_llm(
    user_goal: dict[str, Any],
    produced: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    context: dict[str, Any] | None = None,
) -> CompletionAssessment:
    client = _client(api_key=api_key, base_url=base_url, model=model, llm_settings=llm_settings)
    parsed = _chat_json(
        client,
        build_completion_messages(
            user_goal=_safe_payload(user_goal),
            produced=_safe_payload(produced),
            context=_safe_payload(context or {}),
        ),
        max_tokens=1300,
        stage="completion",
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
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    client = _client(api_key=api_key, base_url=base_url, model=model, llm_settings=llm_settings)
    trace_event("report.llm.start", {"query": query, "user_goal": user_goal, "completion": completion})
    parsed = _chat_json(
        client,
        build_report_messages(
            query=query,
            user_goal=_safe_payload(user_goal),
            result_summary=_safe_payload(result_summary),
            completion=_safe_payload(completion),
            draft_answer=str(draft_answer or "")[:6000],
            reply_language=reply_language,
            context=_safe_payload(context or {}),
        ),
        max_tokens=2000,
        stage="completion",
        operation="report_generation",
    )
    answer = str(parsed.get("answer") or "").strip()
    if not answer:
        raise IntentDecompositionError("LLM report returned an empty answer.")
    trace_event("report.llm.complete", {"answer": answer})
    flow_event(
        "REPORT",
        {
            "report_mode": str((user_goal or {}).get("action") or ""),
            "user_goal": user_goal,
            "completion": completion,
            "answer": answer,
        },
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
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
) -> dict[str, Any]:
    client = _client(api_key=api_key, base_url=base_url, model=model, llm_settings=llm_settings)
    trace_event("semantic_critic.llm.start", {"query": query, "user_goal": user_goal, "completion": completion, "answer": answer})
    parsed = _chat_json(
        client,
        build_critic_messages(
            query=query,
            user_goal=_safe_payload(user_goal),
            completion=_safe_payload(completion),
            answer=str(answer or "")[:7000],
            result_summary=_safe_payload(result_summary),
            reply_language=reply_language,
        ),
        max_tokens=1800,
        stage="critic",
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
    flow_event(
        "CRITIC",
        {
            "critic_type": "llm_semantic_critic",
            "result": result,
            "user_goal": user_goal,
            "completion": completion,
        },
    )
    return result

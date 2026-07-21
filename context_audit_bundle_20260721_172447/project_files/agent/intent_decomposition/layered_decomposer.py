from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any

from agent.console_trace import flow_event, trace_event, trace_exception
from core.llm import LLMService

from agent.intent_decomposition.llm_decomposer import decompose_with_llm
from agent.intent_decomposition.rule_fallback import decompose_with_rules, extract_rule_hints
from agent.intent_decomposition.schemas import (
    DECISION_SOURCE_FALLBACK,
    DECISION_SOURCE_LLM,
    DECISION_SOURCE_RULE,
    IntentDecomposition,
    IntentTask,
    SupervisorDecision,
    TaskPlan,
    UserGoal,
    PROTECTED_OPERATION_TYPES,
    WRITE_INTENTS,
)


def _decompose_with_rules_compat(
    query: str,
    *,
    warning: str,
    context: dict[str, Any] | None,
) -> IntentDecomposition:
    """Pass strategy context while preserving old injected fallback callables."""

    try:
        return decompose_with_rules(
            query,
            warning=warning,
            context=context,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'context'" not in str(exc):
            raise
        return decompose_with_rules(query, warning=warning)


def _hard_rule_task(
    query: str,
    *,
    intent: str,
    parameters: dict[str, Any],
    reason: str,
    operation_type: str = "",
    persistent: bool | None = None,
    apply_now: bool | None = None,
    goal_action: str | None = None,
    goal_objects: list[str] | None = None,
    expected_outputs: list[str] | None = None,
    requires_write: bool | None = None,
    requires_current_state: bool = False,
    requires_external_evidence: bool = False,
    execution_requested: bool = False,
) -> IntentDecomposition:
    task = IntentTask(
        task_id="task_1",
        intent=intent,
        parameters={k: v for k, v in parameters.items() if v not in ("", None)},
        reason=reason,
        confidence=1.0,
        capability_status="executable",
        operation_type=operation_type,
        persistent=persistent,
        apply_now=apply_now,
        expected_outputs=list(expected_outputs or []),
    )
    write_required = bool(
        requires_write
        if requires_write is not None
        else intent in WRITE_INTENTS or operation_type in {"preview", "proposal", "write", "one_time_position_operation"}
    )
    safety_flags = ["hard_control_rule"]
    if write_required:
        safety_flags.append("write_requires_approval_revalidate_commit")
    decision = SupervisorDecision.from_tasks(
        decision_source=DECISION_SOURCE_RULE,
        query_intent=intent,
        tasks=[task],
        confidence=1.0,
        reason=reason,
        safety_flags=safety_flags,
        agent_sequence=["supervisor"],
    )
    return IntentDecomposition(
        query=str(query or ""),
        route_layer="hard_rule",
        tasks=[task],
        is_multi_intent=False,
        confidence=1.0,
        diagnostics={
            "llm_used": False,
            "hard_rule_applied": True,
            "decision_source": DECISION_SOURCE_RULE,
            "fallback_used": False,
        },
        supervisor_decision=decision,
        user_goal=UserGoal.from_dict(
            {
                "raw_message": str(query or ""),
                "goal_summary": goal_action or intent,
                "action": "execute" if execution_requested else ("preview" if write_required else "query"),
                "objects": list(goal_objects or []),
                "expected_outputs": list(expected_outputs or []),
                "requires_current_state": requires_current_state,
                "requires_external_evidence": requires_external_evidence,
                "requires_write": write_required,
                "execution_requested": execution_requested,
                "confidence": 1.0,
                "reason_summary": reason,
                "safety_flags": safety_flags,
            },
            raw_message=str(query or ""),
        ),
        task_plan=TaskPlan.from_dict(
            {
                "tasks": [task.to_dict()],
                "requires_write": write_required,
                "confidence": 1.0,
                "reason_summary": reason,
                "completion_contract": {"must_produce": list(expected_outputs or [])},
            }
        ),
    )


_LANGUAGE_ONLY_MARKERS = {
    "zh": ["中文回复", "用中文回复", "请用中文", "回答中文", "说中文", "reply in chinese", "answer in chinese"],
    "en": ["英文回复", "用英文回复", "请用英文", "回答英文", "说英文", "reply in english", "answer in english"],
}
_LANGUAGE_DOMAIN_MARKERS = [
    "股票", "持仓", "组合", "风险", "排名", "新闻", "证据", "调仓", "资金",
    "stock", "portfolio", "risk", "ranking", "news", "rebalance", "capital",
]


def _detect_language_only(text: str) -> str | None:
    lowered = str(text or "").strip().lower()
    if not lowered or re.search(r"(?<!\d)\d{6}(?!\d)", lowered):
        return None
    matches: list[tuple[int, str]] = []
    for language, markers in _LANGUAGE_ONLY_MARKERS.items():
        for marker in markers:
            position = lowered.rfind(marker)
            if position >= 0:
                matches.append((position, language))
    if not matches or any(marker in lowered for marker in _LANGUAGE_DOMAIN_MARKERS):
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _looks_like_protected_position_preview(text: str) -> bool:
    """Route direct portfolio adjustment requests to the approval preview path."""

    if not text:
        return False
    has_portfolio_object = _contains_any(
        text,
        [
            "持仓",
            "组合",
            "模拟盘",
            "仓位",
            "portfolio",
            "position",
            "holding",
        ],
    )
    explicit_adjustment = _contains_any(
        text,
        [
            "调整",
            "调仓",
            "调一下",
            "减仓",
            "减半",
            "卖出",
            "买入",
            "加入",
            "放入",
            "add",
            "buy",
            "rebalance",
            "adjust",
        ],
    )
    imperative_stability_adjustment = _contains_any(
        text,
        ["把我的持仓", "把当前持仓", "把组合", "把仓位", "make my portfolio", "make the portfolio"],
    ) and _contains_any(
        text,
        [
            "更稳健",
            "更稳",
            "稳健一点",
            "降低风险",
            "降低集中度",
            "分散",
            "more stable",
            "conservative",
            "reduce risk",
        ],
    )
    long_term_policy = _contains_any(
        text,
        [
            "以后",
            "今后",
            "长期",
            "每次",
            "从现在开始",
            "从下次",
            "策略",
            "long term",
            "policy",
        ],
    )
    advice_only = _contains_any(
        text,
        ["建议", "推荐", "只读", "怎么改", "应该修改", "advice", "recommend", "suggest"],
    ) and not _contains_any(
        text,
        ["把我的", "把我现在的", "把当前", "立即", "现在执行", "直接调整", "execute now"],
    )
    return (
        has_portfolio_object
        and (explicit_adjustment or imperative_stability_adjustment)
        and not long_term_policy
        and not advice_only
    )


def _hard_rule_decomposition(query: str) -> IntentDecomposition | None:
    from agent.parameter_extractor import extract_parameters

    text = str(query or "").strip()
    lower = text.lower()
    if not text:
        return _hard_rule_task(text, intent="empty", parameters={}, reason="空请求")
    language = _detect_language_only(text)
    if language:
        return _hard_rule_task(text, intent="set_reply_language", parameters={"reply_language": language}, reason="用户明确切换回复语言")

    params = extract_parameters(text)
    has_rejection_word = any(token in lower for token in ["拒绝", "取消计划", "reject plan", "decline"])
    if has_rejection_word and params.get("plan_id"):
        return _hard_rule_task(
            text,
            intent="reject_execute",
            parameters=params,
            reason="user_rejected_pending_plan",
            operation_type="write",
            apply_now=True,
            goal_action="reject_execute",
            goal_objects=["pending_plan"],
            expected_outputs=["rejected_approval"],
            requires_write=True,
            requires_current_state=False,
            execution_requested=True,
        )
    has_confirmation_word = any(token in lower for token in ["确认", "confirm", "执行"])
    has_confirmation_identity = bool(
        params.get("plan_id")
        or params.get("confirmation_token")
        or re.search(r"agent_plan_[A-Za-z0-9_]+", text)
        or "令牌" in lower
        or "confirmation_token" in lower
    )
    if has_confirmation_word and has_confirmation_identity:
        return _hard_rule_task(
            text,
            intent="confirm_execute",
            parameters=params,
            reason="confirmation_enters_protected_revalidate_commit_flow",
            operation_type="write",
            apply_now=True,
            goal_action="confirm_execute",
            goal_objects=["pending_plan"],
            expected_outputs=["confirmed_commit"],
            requires_write=True,
            requires_current_state=True,
            execution_requested=True,
        )
    if _looks_like_protected_position_preview(text):
        protected_params = {
            **params,
            "query": text,
            "operation_type": "one_time_position_operation",
        }
        return _hard_rule_task(
            text,
            intent="one_time_position_operation",
            parameters=protected_params,
            reason="protected_position_adjustment_preview_required",
            operation_type="one_time_position_operation",
            persistent=False,
            apply_now=True,
            goal_action="preview_position_adjustment",
            goal_objects=["paper_portfolio"],
            expected_outputs=["confirmation_required_proposal"],
            requires_write=True,
            requires_current_state=True,
        )
    stock_codes = list(dict.fromkeys(re.findall(r"(?<!\d)(\d{6})(?!\d)", text)))
    explicit_news_evidence = _contains_any(
        text,
        [
            "新闻",
            "公告",
            "rag",
            "证据",
            "news",
            "announcement",
            "evidence",
        ],
    )
    if stock_codes and explicit_news_evidence:
        return _hard_rule_task(
            text,
            intent="stock_rag",
            parameters={
                **params,
                "stock_code": stock_codes[0],
                "query": text,
                "top_k": 10,
            },
            reason="explicit_stock_news_evidence_query",
            goal_action="query_stock_rag_evidence",
            goal_objects=["stock", "news_evidence"],
            expected_outputs=["market_evidence"],
            requires_external_evidence=True,
        )
    explicit_read_rules = [
        (
            "portfolio_state",
            ["查看当前模拟盘持仓", "查看当前持仓", "当前模拟盘持仓", "模拟盘状态", "账户摘要", "current positions"],
            "query_portfolio_state",
            ["portfolio"],
            ["portfolio_state"],
        ),
        (
            "ranking",
            ["查看最新预测排名", "最新预测排名", "预测排名前", "最新排名", "top 10 ranking", "top10 ranking"],
            "query_ranking",
            ["ranking"],
            ["ranking"],
        ),
    ]
    is_compound_read = _contains_any(text, ["并", "同时", "以及", "然后", " and ", " also "])
    for intent, markers, goal_action, objects, outputs in explicit_read_rules:
        if _contains_any(text, markers) and not is_compound_read:
            return _hard_rule_task(
                text,
                intent=intent,
                parameters=params,
                reason="explicit_single_read_intent",
                goal_action=goal_action,
                goal_objects=objects,
                expected_outputs=outputs,
                requires_current_state=intent in {"portfolio_state", "portfolio_risk"},
                requires_external_evidence=intent == "ranking",
            )
    return None


def _decision_intent(decomposition: IntentDecomposition) -> str:
    if decomposition.need_clarification:
        return "clarification_required"
    if not decomposition.tasks:
        error_code = str((decomposition.diagnostics or {}).get("error_code") or "")
        return "llm_insufficient_balance" if error_code == "insufficient_balance" else "unsupported"
    return "multi_intent" if len(decomposition.tasks) > 1 else decomposition.tasks[0].intent


def _agent_sequence_for_tasks(tasks: list[IntentTask]) -> list[str]:
    try:
        from agent.agent_specs import SUPERVISOR, role_for_intent
    except Exception:
        return ["supervisor"]
    sequence = [SUPERVISOR]
    for task in tasks:
        role = role_for_intent(task.intent)
        if role and role not in sequence:
            sequence.append(role)
    return sequence


def _repair_fallback_completeness(query: str, decomposition: IntentDecomposition) -> IntentDecomposition:
    if decomposition.route_layer not in {"rule_fallback", "fallback"}:
        return decomposition
    text = str(query or "")
    looks_like_recommendation = any(marker in text for marker in ["推荐", "建议", "更稳健", "调仓建议", "优化", "修改成什么样"])
    intents = {task.intent for task in decomposition.tasks}
    if not looks_like_recommendation or {"portfolio_risk", "ranking"}.issubset(intents):
        return decomposition
    tasks = [
        IntentTask(task_id="task_1", intent="portfolio_state", confidence=0.86, capability_status="executable"),
        IntentTask(task_id="task_2", intent="portfolio_risk", depends_on=["task_1"], confidence=0.86, capability_status="executable"),
        IntentTask(task_id="task_3", intent="ranking", parameters={"top_k": 10}, confidence=0.86, capability_status="executable"),
    ]
    diagnostics = {
        **dict(decomposition.diagnostics or {}),
        "completeness_guard_triggered": True,
        "auto_added_tasks": ["portfolio_risk", "ranking"],
        "denied_low_priority_rules": ["portfolio_state_keyword"],
        "mcp_candidate_view": {"entered": False},
    }
    return replace(
        decomposition,
        tasks=tasks,
        is_multi_intent=True,
        diagnostics=diagnostics,
    )


def _with_supervisor_decision(decomposition: IntentDecomposition, *, source: str, reason: str, extra_diagnostics: dict[str, Any] | None = None) -> IntentDecomposition:
    diagnostics = {**dict(decomposition.diagnostics or {}), **dict(extra_diagnostics or {}), "decision_source": source}
    flags = ["llm_first_business_semantics"] if source == DECISION_SOURCE_LLM else ["hard_control_rule"]
    if any(task.intent in WRITE_INTENTS or task.operation_type in WRITE_INTENTS for task in decomposition.tasks):
        flags.append("write_requires_approval_revalidate_commit")
    decision = SupervisorDecision.from_tasks(
        decision_source=source,
        query_intent=_decision_intent(decomposition),
        tasks=list(decomposition.tasks),
        confidence=decomposition.confidence,
        reason=reason,
        safety_flags=flags,
        agent_sequence=_agent_sequence_for_tasks(list(decomposition.tasks)),
    )
    return replace(decomposition, diagnostics=diagnostics, supervisor_decision=decision)


def _is_insufficient_balance_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in ["insufficient balance", "insufficient_balance", "余额不足", "账户余额不足", "http 402", "status code: 402", "error code: 402"])


def _llm_error_decomposition(
    query: str,
    *,
    error_code: str,
    message: str,
    llm_identity: dict[str, Any] | None,
    hints: dict[str, Any],
    llm_called: bool,
) -> IntentDecomposition:
    return IntentDecomposition(
        query=str(query or ""),
        route_layer="llm_error",
        tasks=[],
        is_multi_intent=False,
        need_clarification=False,
        unsupported_reason=message,
        confidence=0.0,
        warnings=[],
        diagnostics={
            "llm_used": llm_called,
            "llm_planner_called": llm_called,
            "fatal_error": True,
            "error_code": error_code,
            "llm_identity": dict(llm_identity or {}),
            "fallback_used": False,
            "business_rule_fallback_disabled": True,
            "rule_hints": hints,
        },
    )


def decompose_intent(
    query: str,
    *,
    llm_service: LLMService | None = None,
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    enable_llm: bool = True,
) -> IntentDecomposition:
    trace_event("intent_decomposition.start", {"query": query, "enable_llm": enable_llm}, run_id=str((context or {}).get("run_id") or ""))
    hard_rule = _hard_rule_decomposition(query)
    if hard_rule is not None:
        flow_event(
            "RULE_HINTS",
            {
                "mode": "hard_control_rule",
                "authoritative": True,
                "query": str(query or ""),
                "hard_rule_result": hard_rule.to_dict(),
            },
            run_id=str((context or {}).get("run_id") or ""),
        )
        return hard_rule

    hints = extract_rule_hints(query).to_dict()
    flow_event(
        "RULE_HINTS",
        {
            "mode": "business_advisory_hints",
            "authoritative": False,
            "query": str(query or ""),
            "rule_hints": hints,
            "next_step": "send original query + Context Packet + advisory hints to LLM UserGoal/TaskPlan parser",
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    if not enable_llm:
        return _with_supervisor_decision(
            _repair_fallback_completeness(query, _decompose_with_rules_compat(query, warning="llm_disabled", context=context)),
            source=DECISION_SOURCE_FALLBACK,
            reason="LLM disabled; deterministic fallback selected only registered read/proposal tasks.",
        )
    if False and not enable_llm:
        return _with_supervisor_decision(
            _llm_error_decomposition(query, error_code="llm_disabled", message="LLM意图识别已禁用，业务请求未执行规则兜底。", llm_identity={}, hints=hints, llm_called=False),
            source=DECISION_SOURCE_LLM,
            reason="LLM-first 模式要求业务请求必须由 LLM 解析",
        )

    if llm_service is None or not llm_service.is_available:
        return _with_supervisor_decision(
            _repair_fallback_completeness(query, _decompose_with_rules_compat(query, warning="llm_service_unavailable", context=context)),
            source=DECISION_SOURCE_FALLBACK,
            reason="LLM service unavailable; deterministic fallback selected only registered read/proposal tasks.",
        )
    if False and llm_service is None:
        return _with_supervisor_decision(
            _llm_error_decomposition(query, error_code="llm_service_unavailable", message="未配置可用的 LLM Service，无法可靠理解本次业务请求。", llm_identity={}, hints=hints, llm_called=False),
            source=DECISION_SOURCE_LLM,
            reason="LLM-first 模式禁止业务关键词回退",
        )

    started = time.perf_counter()
    context_packet = dict(context or {})
    context_packet["rule_hints"] = hints
    try:
        decomposition = decompose_with_llm(
            query,
            llm_service=llm_service,
            reply_language=reply_language,
            context=context_packet,
            rule_hints=hints,
        )
        if any(
            task.intent in WRITE_INTENTS or task.operation_type in PROTECTED_OPERATION_TYPES
            for task in decomposition.tasks
        ):
            fallback = _repair_fallback_completeness(
                query,
                _decompose_with_rules_compat(query, warning="LLM意图拆解失败：写任务不能由 LLM 绕过硬保护路由", context=context),
            )
            return _with_supervisor_decision(
                fallback,
                source=DECISION_SOURCE_FALLBACK,
                reason="LLM proposed a protected write outside the hard safety chain; deterministic fallback selected.",
                extra_diagnostics={
                    "llm_planner_called": True,
                    "llm_write_plan_blocked": True,
                    "fallback_used": True,
                    "llm_planner_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                },
            )
        return _with_supervisor_decision(
            decomposition,
            source=DECISION_SOURCE_LLM,
            reason="业务 UserGoal、TaskPlan、GoalReview 和 PlanReview 均由 LLM 生成",
            extra_diagnostics={
                "llm_planner_called": True,
                "llm_planner_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "llm_planner_token_estimate": max(1, (len(str(query)) + len(str(context_packet))) // 4),
                "rule_hints": hints,
                "fallback_used": False,
            },
        )
    except Exception as exc:
        code = "insufficient_balance" if _is_insufficient_balance_error(exc) else "llm_planning_failed"
        if code != "insufficient_balance":
            return _with_supervisor_decision(
                _repair_fallback_completeness(query, _decompose_with_rules_compat(query, warning=f"llm_planning_failed:{type(exc).__name__}", context=context)),
                source=DECISION_SOURCE_FALLBACK,
                reason="LLM planning failed; deterministic fallback selected only registered read/proposal tasks.",
                extra_diagnostics={"llm_planner_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3)},
            )
        message = "大模型账户余额不足，无法完成本次意图识别。" if code == "insufficient_balance" else f"LLM意图识别失败：{type(exc).__name__}: {exc}"
        return _with_supervisor_decision(
            _llm_error_decomposition(
                query,
                error_code=code,
                message=message,
                llm_identity=(
                    {
                        "profile_id": llm_service.profile_id,
                        "config_hash": llm_service.config_hash,
                    }
                    if llm_service is not None
                    else {}
                ),
                hints=hints,
                llm_called=True,
            ),
            source=DECISION_SOURCE_LLM,
            reason="LLM 失败后停止业务执行，不使用关键词规则兜底",
            extra_diagnostics={"llm_planner_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3)},
        )

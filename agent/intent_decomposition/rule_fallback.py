from __future__ import annotations

import re
from typing import Any

from agent.intent_decomposition.schemas import (
    IntentDecomposition,
    IntentTask,
    RuleHint,
    RuleHints,
    TaskPlan,
    UserGoal,
)


_HINT_PATTERNS: list[tuple[str, str, list[str], float]] = [
    ("action", "compare", ["对比", "比较", "相比", "差异", "区别", "compare", "versus", " vs "], 0.95),
    ("action", "analyze", ["分析", "评估", "风险", "review", "analyze", "evaluate"], 0.78),
    ("action", "recommend", ["推荐", "建议", "更稳健", "优化", "怎么改", "recommend", "suggest", "optimize"], 0.82),
    ("action", "explain", ["为什么", "原因", "解释", "说明", "why", "reason"], 0.86),
    ("action", "execute", ["确认执行", "按这个方案执行", "execute", "confirm"], 0.85),
    ("object", "portfolio", ["持仓", "组合", "模拟盘", "账户", "portfolio", "position", "holding"], 0.86),
    ("object", "stock", ["股票", "个股", "stock"], 0.68),
    ("constraint", "risk", ["风险", "回撤", "集中度", "分散", "risk", "drawdown"], 0.83),
    ("constraint", "more_stable", ["稳健", "更稳", "保守", "stable", "robust", "conservative"], 0.87),
    ("reference", "current_state", ["现在", "当前", "目前", "current", "now"], 0.82),
    ("evidence", "external_evidence", ["新闻", "公告", "证据", "rag", "news", "evidence"], 0.82),
    ("write_risk", "position_change", ["买入", "卖出", "加仓", "减仓", "清仓", "调到", "仓位", "buy", "sell", "increase", "reduce"], 0.86),
    ("write_risk", "long_term_policy", ["以后", "长期", "每次", "从现在开始", "策略", "policy", "long term"], 0.84),
]


def _extract_entities(text: str) -> dict[str, Any]:
    stock_codes = list(dict.fromkeys(re.findall(r"(?<!\d)(\d{6})(?!\d)", text)))
    percentages = list(dict.fromkeys(re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", text)))
    amounts = list(dict.fromkeys(re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:元|万|万元|亿|亿元)", text)))
    dates = list(dict.fromkeys(re.findall(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text)))
    return {"stock_codes": stock_codes, "percentages": percentages, "amounts": amounts, "dates": dates}


def extract_rule_hints(query: str) -> RuleHints:
    text = str(query or "")
    lower = text.lower()
    hints: list[RuleHint] = []
    for category, value, markers, confidence in _HINT_PATTERNS:
        for marker in markers:
            if marker.lower() in lower:
                hints.append(RuleHint(category=category, value=value, matched_text=marker, confidence=confidence))
                break
    return RuleHints(hints=hints, explicit_entities=_extract_entities(text), warnings=[])


def decompose_with_rules(
    query: str,
    *,
    warning: str = "",
    context: dict[str, Any] | None = None,
) -> IntentDecomposition:
    """Deterministic fallback for registered Agent capabilities.

    The fallback only creates read tasks, clarification tasks, or confirmation-
    required proposal tasks. It never commits a write and never bypasses the
    protected approval/revalidate/commit boundary.
    """

    text = str(query or "").strip()
    hints = extract_rule_hints(text)
    tasks, goal_payload, clarification = _deterministic_plan(
        text,
        context=context,
    )
    warnings = [warning] if warning else []
    diagnostics = {
        "rule_hints": hints.to_dict(),
        "fallback_used": True,
        "decision_source": "fallback",
        "business_rule_fallback_disabled": False,
        **_guard_diagnostics(text, tasks),
    }
    if clarification:
        return IntentDecomposition(
            query=text,
            route_layer="rule_fallback",
            tasks=[],
            is_multi_intent=False,
            need_clarification=True,
            clarification_question=clarification,
            confidence=0.72,
            warnings=warnings,
            diagnostics=diagnostics,
            user_goal=UserGoal.from_dict(goal_payload, raw_message=text),
            task_plan=TaskPlan.from_dict({"tasks": [], "confidence": 0.72, "reason_summary": "deterministic_clarification"}),
        )

    confidence = 0.82 if tasks else 0.45
    return IntentDecomposition(
        query=text,
        route_layer="rule_fallback",
        tasks=tasks,
        is_multi_intent=len(tasks) > 1,
        need_clarification=False,
        unsupported_reason="" if tasks else "LLM 不可用，且确定性兜底无法识别可安全执行的已注册能力。",
        confidence=confidence,
        warnings=warnings,
        diagnostics=diagnostics,
        user_goal=UserGoal.from_dict(goal_payload, raw_message=text),
        task_plan=TaskPlan.from_dict(
            {
                "tasks": [task.to_dict() for task in tasks],
                "requires_write": any(task.intent in {"one_time_position_operation", "capital_management", "backfill"} for task in tasks),
                "confidence": confidence,
                "reason_summary": "deterministic_registered_capability_fallback",
                "completion_contract": {"must_produce": goal_payload.get("expected_outputs") or []},
            }
        ),
    )


def _has_any(text: str, markers: list[str]) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def _task(
    task_id: str,
    intent: str,
    *,
    parameters: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    reason: str = "deterministic_fallback",
    operation_type: str = "",
    persistent: bool | None = None,
    apply_now: bool | None = None,
) -> IntentTask:
    return IntentTask(
        task_id=task_id,
        intent=intent,
        parameters={key: value for key, value in dict(parameters or {}).items() if value not in ("", None)},
        depends_on=list(depends_on or []),
        reason=reason,
        confidence=0.86,
        capability_status="executable",
        operation_type=operation_type,
        persistent=persistent,
        apply_now=apply_now,
    )


def _goal(
    text: str,
    *,
    action: str,
    objects: list[str],
    expected_outputs: list[str],
    requires_current_state: bool = False,
    requires_external_evidence: bool = False,
    requires_write: bool = False,
    execution_requested: bool = False,
    clarification_question: str = "",
) -> dict[str, Any]:
    return {
        "raw_message": text,
        "goal_summary": action,
        "action": "clarify" if clarification_question else ("preview" if requires_write else "query"),
        "objects": objects,
        "constraints": [],
        "expected_outputs": expected_outputs,
        "requires_current_state": requires_current_state,
        "requires_external_evidence": requires_external_evidence,
        "requires_write": requires_write,
        "execution_requested": execution_requested,
        "need_clarification": bool(clarification_question),
        "clarification_question": clarification_question,
        "confidence": 0.86 if not clarification_question else 0.72,
        "reason_summary": "deterministic fallback for registered stock/portfolio capabilities",
        "safety_flags": ["fallback_no_direct_write"] if requires_write else ["fallback_readonly"],
    }


def _stock_codes(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"(?<!\d)(\d{6})(?!\d)", text)))


def _deterministic_plan(
    text: str,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[list[IntentTask], dict[str, Any], str]:
    from agent.parameter_extractor import extract_parameters

    params = extract_parameters(text)
    ranking_parameters = (
        {"top_k": params["top_k"]}
        if params.get("top_k") not in (None, "")
        else {}
    )
    codes = _stock_codes(text)
    has_portfolio = _has_any(text, ["持仓", "组合", "模拟盘", "账户", "资产", "portfolio", "position", "holding", "account"])
    has_risk = _has_any(text, ["风险", "回撤", "集中", "稳健", "risk", "drawdown", "stable", "robust"])
    has_ranking = _has_any(text, ["排名", "排行", "前十", "top", "推荐股票", "模型推荐", "ranking"])
    has_evidence = _has_any(text, ["新闻", "公告", "rag", "证据", "news", "evidence"])
    has_compare = _has_any(text, ["比较", "对比", "相比", "compare", "versus", " vs "])
    has_advice = _has_any(text, ["建议", "推荐", "调仓建议", "优化", "更稳健", "稳健一点", "recommend", "suggest", "optimize"])
    explicit_write = _has_any(
        text,
        [
            "加入",
            "放入",
            "加到",
            "卖出",
            "买入",
            "调整",
            "调仓",
            "调一下",
            "减半",
            "减仓",
            "加仓",
            "清仓",
            "调到",
            "降到",
            "把我的持仓调整",
            "把当前持仓调整",
            "修改持仓",
            "执行调整",
            "sell",
            "buy",
            "reduce",
            "trim",
        ],
    )
    if explicit_write and _has_any(text, ["建议", "推荐", "只读", "怎么改", "应该修改", "advice", "suggest"]):
        direct_execution_language = _has_any(
            text,
            ["把我的", "把我现在的", "把当前", "立即", "现在执行", "确认执行", "直接调整", "execute now"],
        )
        if not direct_execution_language:
            explicit_write = False
    strategy_context = dict(
        (context or {}).get("strategy_conversation_context") or {}
    )
    active_proposal = dict(strategy_context.get("active_proposal") or {})
    strategy_change = bool(active_proposal) or _has_any(
        text,
        ["以后", "今后", "后续", "长期", "每次", "从现在开始", "从下次", "策略"],
    )

    if strategy_change:
        parameters = {
            **params,
            "query": text,
            "operation_type": "strategy_change",
            "conversation_action": "llm_unavailable",
            "proposal_id": str(active_proposal.get("proposal_id") or ""),
            "original_request": text,
            "user_feedback": text,
        }
        task = _task(
            "task_1",
            "strategy_change",
            parameters=parameters,
            operation_type="strategy_change",
            persistent=True,
            apply_now=False,
            reason="llm_unavailable_keep_strategy_draft",
        )
        return [task], _goal(
            text,
            action="keep_strategy_draft",
            objects=["paper_strategy"],
            expected_outputs=["strategy_proposal_draft"],
            requires_current_state=True,
            requires_write=False,
        ), ""

    if _has_any(text, ["按这个方案执行", "确认执行", "执行这个方案"]) and not params.get("plan_id"):
        task = _task(
            "task_1",
            "confirm_execute",
            parameters=params,
            operation_type="write",
            persistent=False,
            apply_now=True,
            reason="execution_requested_without_pending_plan_identity",
        )
        return [task], _goal(
            text,
            action="prepare_execution_confirmation",
            objects=["pending_plan"],
            expected_outputs=["confirmed_commit"],
            requires_current_state=True,
            requires_write=True,
            execution_requested=True,
        ), ""

    if _has_any(text, ["为什么这样调整", "为什么这么调整", "为什么这样", "解释这个调整"]):
        tasks = [
            _task("task_1", "portfolio_state"),
            _task("task_2", "portfolio_risk", depends_on=["task_1"]),
            _task("task_3", "ranking", parameters=ranking_parameters),
        ]
        return tasks, _goal(
            text,
            action="explain_previous_plan",
            objects=["previous_plan"],
            expected_outputs=["target_portfolio", "reasons", "risk_analysis"],
            requires_current_state=True,
            requires_external_evidence=True,
        ), ""

    if has_compare and len(codes) < 2:
        question = "请补充要比较的两只股票代码，例如：比较 600519 和 000001 哪只更适合。"
        return [], _goal(text, action="clarify_stock_compare", objects=["stock"], expected_outputs=[], clarification_question=question), question

    if explicit_write:
        parameters = {**params, "query": text, "operation_type": "one_time_position_operation"}
        task = _task(
            "task_1",
            "one_time_position_operation",
            parameters=parameters,
            operation_type="one_time_position_operation",
            persistent=False,
            apply_now=True,
            reason="confirmation_required_one_time_position_preview",
        )
        return [task], _goal(
            text,
            action="preview_position_adjustment",
            objects=["paper_portfolio"],
            expected_outputs=["confirmation_required_proposal"],
            requires_current_state=True,
            requires_write=True,
        ), ""

    if has_compare and len(codes) >= 2:
        tasks = [
            _task("task_1", "stock_analysis", parameters={"stock_code": codes[0]}),
            _task("task_2", "stock_analysis", parameters={"stock_code": codes[1]}),
        ]
        return tasks, _goal(text, action="compare_stocks", objects=["stock"], expected_outputs=["stock_comparison"], requires_external_evidence=True), ""

    if has_portfolio and has_risk and not has_advice:
        tasks = [
            _task("task_1", "portfolio_state"),
            _task("task_2", "portfolio_risk", depends_on=["task_1"]),
        ]
        return tasks, _goal(text, action="analyze_portfolio_risk", objects=["portfolio"], expected_outputs=["portfolio_state", "risk_analysis"], requires_current_state=True), ""

    if has_portfolio and (has_advice or _has_any(text, ["修改成什么样", "怎么改", "应该修改"])):
        tasks = [
            _task("task_1", "portfolio_state"),
            _task("task_2", "portfolio_risk", depends_on=["task_1"]),
            _task("task_3", "ranking", parameters=ranking_parameters),
        ]
        action = "recommend_portfolio_adjustment" if _has_any(text, ["修改成什么样", "怎么改", "应该修改", "调仓建议"]) else "recommend_portfolio"
        return tasks, _goal(
            text,
            action=action,
            objects=["portfolio"],
            expected_outputs=["target_portfolio", "reasons", "risk_analysis", "market_evidence"],
            requires_current_state=True,
            requires_external_evidence=True,
        ), ""

    if has_portfolio:
        return [_task("task_1", "portfolio_state")], _goal(text, action="query_portfolio_state", objects=["portfolio"], expected_outputs=["portfolio_state"], requires_current_state=True), ""

    if has_ranking or has_evidence:
        tasks: list[IntentTask] = []
        if has_ranking or not codes:
            tasks.append(_task("task_1", "ranking", parameters=ranking_parameters))
        if has_evidence and codes:
            tasks.append(_task(f"task_{len(tasks) + 1}", "stock_rag", parameters={"stock_code": codes[0], "query": text, "top_k": 10}))
        return tasks, _goal(text, action="query_market_evidence", objects=["market"], expected_outputs=["market_evidence"], requires_external_evidence=True), ""

    if codes:
        return [_task("task_1", "stock_analysis", parameters={"stock_code": codes[0]})], _goal(text, action="analyze_stock", objects=["stock"], expected_outputs=["stock_analysis"], requires_external_evidence=True), ""

    return [_task("task_1", "general_help")], _goal(text, action="fallback_intent", objects=["help"], expected_outputs=["help_text"]), ""


def _guard_diagnostics(text: str, tasks: list[IntentTask]) -> dict[str, Any]:
    intents = [task.intent for task in tasks]
    has_recommendation = _has_any(text, ["建议", "推荐", "调仓建议", "更稳健", "优化"])
    completeness_guard = has_recommendation and "portfolio_state" in intents and len(intents) > 1
    return {
        "rule_hits": intents,
        "completeness_guard_triggered": completeness_guard,
        "auto_added_tasks": ["portfolio_risk", "ranking"] if completeness_guard else [],
        "denied_low_priority_rules": ["portfolio_state_keyword"] if completeness_guard else [],
        "mcp_candidate_view": {"entered": False},
    }

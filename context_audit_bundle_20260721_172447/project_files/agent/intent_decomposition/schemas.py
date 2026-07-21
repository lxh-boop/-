from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DECISION_SOURCE_RULE = "rule"
DECISION_SOURCE_LLM = "llm"
DECISION_SOURCE_FALLBACK = "fallback"
DECISION_SOURCES = {
    DECISION_SOURCE_RULE,
    DECISION_SOURCE_LLM,
    DECISION_SOURCE_FALLBACK,
}

HIGH_LEVEL_ACTIONS = {
    "query",
    "analyze",
    "compare",
    "explain",
    "recommend",
    "construct",
    "preview",
    "execute",
    "modify_policy",
    "clarify",
}

EXECUTABLE_INTENTS = {
    "ranking",
    "portfolio_state",
    "portfolio_risk",
    "stock_analysis",
    "stock_news",
    "stock_rag",
    "position_recommendation",
    "replacement_recommendation",
    "preview_add_stock",
    "adjust_position",
    "one_time_position_operation",
    "strategy_change",
    "confirm_execute",
    "reject_execute",
    "capital_management",
    "scheduler_status",
    "backfill",
    "report",
    "report_latest",
    "empty",
    "general_help",
    "set_reply_language",
    "stock_lookup",
    "classic_stock_score",
    "classic_ranking",
    "python_sandbox_analysis",
    "portfolio.design_target_portfolio",
    "portfolio.construct_target_portfolio",
    "portfolio.load_target_portfolio",
    "portfolio.compare_portfolios",
}

KNOWN_INTENTS = EXECUTABLE_INTENTS | {
    "user_profile",
    "model_zoo",
    "backtest",
    "compare_models",
    "news_mapping",
    "market_context",
    "daily_report",
}

MAX_TASKS = 12
MIN_LLM_CONFIDENCE = 0.60

WRITE_INTENTS = {
    "preview_add_stock",
    "adjust_position",
    "one_time_position_operation",
    "confirm_execute",
    "reject_execute",
    "capital_management",
    "backfill",
}

PROTECTED_OPERATION_TYPES = {"preview", "proposal", "write"}

SENSITIVE_PARAMETER_NAMES = {
    "api_key",
    "secret",
    "password",
    "authorization",
    "cookie",
    "db_path",
    "database_path",
    "local_path",
    "confirmation_token",
}


def _clean_parameters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key or "").strip()
        if not name or item in ("", None):
            continue
        cleaned[name] = item
    return cleaned


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _confidence(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 1.0))


@dataclass(frozen=True)
class RuleHint:
    category: str
    value: str
    matched_text: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleHint":
        return cls(
            category=str(data.get("category") or "").strip(),
            value=str(data.get("value") or "").strip(),
            matched_text=str(data.get("matched_text") or "").strip()[:200],
            confidence=_confidence(data.get("confidence")),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuleHints:
    hints: list[RuleHint] = field(default_factory=list)
    explicit_entities: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RuleHints":
        payload = dict(data or {})
        raw = payload.get("hints") if isinstance(payload.get("hints"), list) else []
        return cls(
            hints=[RuleHint.from_dict(item) for item in raw if isinstance(item, dict)],
            explicit_entities=dict(payload.get("explicit_entities") or {}),
            warnings=_clean_string_list(payload.get("warnings")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hints": [item.to_dict() for item in self.hints],
            "explicit_entities": dict(self.explicit_entities),
            "warnings": list(self.warnings),
            "advisory_only": True,
        }


@dataclass(frozen=True)
class FollowUpReference:
    is_follow_up: bool = False
    reference_source: str = ""
    reference_turn_ids: list[str] = field(default_factory=list)
    reference_artifact_refs: list[str] = field(default_factory=list)
    reference_summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FollowUpReference":
        payload = dict(data or {})
        return cls(
            is_follow_up=bool(payload.get("is_follow_up", False)),
            reference_source=str(payload.get("reference_source") or "").strip(),
            reference_turn_ids=_clean_string_list(payload.get("reference_turn_ids")),
            reference_artifact_refs=_clean_string_list(payload.get("reference_artifact_refs")),
            reference_summary=str(payload.get("reference_summary") or "").strip()[:1000],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserGoal:
    raw_message: str
    goal_summary: str
    action: str
    objects: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    follow_up: FollowUpReference = field(default_factory=FollowUpReference)
    requires_current_state: bool = False
    requires_external_evidence: bool = False
    requires_write: bool = False
    execution_requested: bool = False
    missing_information: list[str] = field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str = ""
    confidence: float = 0.0
    reason_summary: str = ""
    safety_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, raw_message: str = "") -> "UserGoal":
        payload = dict(data or {})
        action = str(payload.get("action") or "clarify").strip()
        if action not in HIGH_LEVEL_ACTIONS:
            action = "clarify"
        missing_information = _clean_string_list(payload.get("missing_information"))
        confidence = _confidence(payload.get("confidence"))
        need_clarification = bool(payload.get("need_clarification", False))
        # Generic uncertainty guard only: it does not choose a business intent.
        # If the LLM itself reports missing information or low confidence, the
        # request must be clarified instead of guessing from keywords/history.
        if missing_information or confidence < MIN_LLM_CONFIDENCE or action == "clarify":
            need_clarification = True
        question = str(payload.get("clarification_question") or "").strip()[:500]
        if need_clarification and not question:
            if missing_information:
                question = "请补充以下必要信息：" + "、".join(missing_information[:5]) + "。"
            else:
                question = "我还不能可靠确定你的具体目标，请补充要处理的对象、范围或期望结果。"
        return cls(
            raw_message=str(payload.get("raw_message") or raw_message or ""),
            goal_summary=str(payload.get("goal_summary") or "").strip()[:1000],
            action=action,
            objects=_clean_string_list(payload.get("objects")),
            constraints=_clean_string_list(payload.get("constraints")),
            expected_outputs=_clean_string_list(payload.get("expected_outputs")),
            follow_up=FollowUpReference.from_dict(payload.get("follow_up")),
            requires_current_state=bool(payload.get("requires_current_state", False)),
            requires_external_evidence=bool(payload.get("requires_external_evidence", False)),
            requires_write=bool(payload.get("requires_write", False)),
            execution_requested=bool(payload.get("execution_requested", False)),
            missing_information=missing_information,
            need_clarification=need_clarification,
            clarification_question=question,
            confidence=confidence,
            reason_summary=str(payload.get("reason_summary") or "").strip()[:800],
            safety_flags=_clean_string_list(payload.get("safety_flags")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["follow_up"] = self.follow_up.to_dict()
        return data


@dataclass(frozen=True)
class GoalReview:
    status: str = "pass"
    issues: list[str] = field(default_factory=list)
    revised_user_goal: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GoalReview":
        payload = dict(data or {})
        status = str(payload.get("status") or "pass").strip().lower()
        if status not in {"pass", "revise", "clarify", "block"}:
            status = "revise"
        return cls(
            status=status,
            issues=_clean_string_list(payload.get("issues")),
            revised_user_goal=dict(payload.get("revised_user_goal") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentTask:
    task_id: str
    intent: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    capability_status: str = "executable"
    operation_type: str = ""
    persistent: bool | None = None
    apply_now: bool | None = None
    expected_outputs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> "IntentTask":
        intent = str(data.get("intent") or data.get("capability") or "").strip()
        if intent not in KNOWN_INTENTS:
            raise ValueError(f"unsupported_intent:{intent}")
        task_id = str(data.get("task_id") or f"task_{index}").strip() or f"task_{index}"
        capability_status = "executable" if intent in EXECUTABLE_INTENTS else "known_not_integrated"
        return cls(
            task_id=task_id,
            intent=intent,
            parameters=_clean_parameters(data.get("parameters")),
            depends_on=_clean_string_list(data.get("depends_on")),
            reason=str(data.get("reason") or "").strip()[:600],
            confidence=_confidence(data.get("confidence")),
            capability_status=capability_status,
            operation_type=str(data.get("operation_type") or "").strip(),
            persistent=bool(data["persistent"]) if "persistent" in data and data["persistent"] is not None else None,
            apply_now=bool(data["apply_now"]) if "apply_now" in data and data["apply_now"] is not None else None,
            expected_outputs=_clean_string_list(data.get("expected_outputs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskPlan:
    tasks: list[IntentTask] = field(default_factory=list)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    requires_write: bool = False
    need_clarification: bool = False
    clarification_question: str = ""
    confidence: float = 0.0
    reason_summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskPlan":
        payload = dict(data or {})
        raw_tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
        tasks: list[IntentTask] = []
        for index, item in enumerate(raw_tasks[:MAX_TASKS], start=1):
            if not isinstance(item, dict):
                continue
            tasks.append(IntentTask.from_dict(item, index))
        ids = {item.task_id for item in tasks}
        normalised: list[IntentTask] = []
        for item in tasks:
            deps = [dep for dep in item.depends_on if dep in ids and dep != item.task_id]
            normalised.append(IntentTask(**{**item.to_dict(), "depends_on": deps}))
        confidence = _confidence(payload.get("confidence"))
        need_clarification = bool(payload.get("need_clarification", False))
        question = str(payload.get("clarification_question") or "").strip()[:500]
        if confidence < MIN_LLM_CONFIDENCE:
            need_clarification = True
        if need_clarification and not question:
            question = "当前任务计划仍存在不确定信息，请补充后再执行。"
        inferred_write = any(
            item.intent in WRITE_INTENTS or item.operation_type in PROTECTED_OPERATION_TYPES
            for item in normalised
        )
        return cls(
            tasks=normalised,
            completion_contract=dict(payload.get("completion_contract") or {}),
            requires_write=bool(payload.get("requires_write", inferred_write)),
            need_clarification=need_clarification,
            clarification_question=question,
            confidence=confidence,
            reason_summary=str(payload.get("reason_summary") or "").strip()[:800],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [item.to_dict() for item in self.tasks],
            "dependencies": {item.task_id: list(item.depends_on) for item in self.tasks},
            "completion_contract": dict(self.completion_contract),
            "requires_write": self.requires_write,
            "need_clarification": self.need_clarification,
            "clarification_question": self.clarification_question,
            "confidence": self.confidence,
            "reason_summary": self.reason_summary,
        }


@dataclass(frozen=True)
class PlanReview:
    status: str = "pass"
    missing_tasks: list[str] = field(default_factory=list)
    unexpected_tasks: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    revised_task_plan: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PlanReview":
        payload = dict(data or {})
        status = str(payload.get("status") or "pass").strip().lower()
        if status not in {"pass", "revise", "clarify", "block"}:
            status = "revise"
        return cls(
            status=status,
            missing_tasks=_clean_string_list(payload.get("missing_tasks")),
            unexpected_tasks=_clean_string_list(payload.get("unexpected_tasks")),
            missing_outputs=_clean_string_list(payload.get("missing_outputs")),
            issues=_clean_string_list(payload.get("issues")),
            revised_task_plan=dict(payload.get("revised_task_plan") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompletionAssessment:
    status: str
    produced_outputs: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    conflict_outputs: list[str] = field(default_factory=list)
    invalid_reasons: list[str] = field(default_factory=list)
    next_action: str = "finish"
    reason_summary: str = ""
    confidence: float = 0.0
    llm_used: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, *, llm_used: bool = True) -> "CompletionAssessment":
        payload = dict(data or {})
        status = str(payload.get("status") or payload.get("completion_status") or "unknown").strip().lower()
        if status not in {"complete", "partial", "missing", "conflict", "invalid", "unknown"}:
            status = "unknown"
        action = str(payload.get("next_action") or "finish").strip().lower()
        if action not in {"finish", "replan_readonly", "ask_user", "block", "wait_approval", "report_limitation"}:
            action = "report_limitation"
        return cls(
            status=status,
            produced_outputs=_clean_string_list(payload.get("produced_outputs")),
            missing_outputs=_clean_string_list(payload.get("missing_outputs")),
            conflict_outputs=_clean_string_list(payload.get("conflict_outputs") or payload.get("conflicts")),
            invalid_reasons=_clean_string_list(payload.get("invalid_reasons")),
            next_action=action,
            reason_summary=str(payload.get("reason_summary") or "").strip()[:1000],
            confidence=_confidence(payload.get("confidence")),
            llm_used=llm_used,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupervisorDecision:
    decision_source: str
    intent: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    agent_sequence: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    requires_write: bool = False
    confidence: float = 0.0
    reason: str = ""
    safety_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_tasks(
        cls,
        *,
        decision_source: str,
        query_intent: str,
        tasks: list[IntentTask],
        confidence: float,
        reason: str,
        safety_flags: list[str] | None = None,
        agent_sequence: list[str] | None = None,
    ) -> "SupervisorDecision":
        source = decision_source if decision_source in DECISION_SOURCES else DECISION_SOURCE_FALLBACK
        return cls(
            decision_source=source,
            intent=str(query_intent or ""),
            tasks=[item.to_dict() for item in tasks],
            agent_sequence=list(agent_sequence or []),
            dependencies={item.task_id: list(item.depends_on) for item in tasks},
            requires_write=any(
                item.intent in WRITE_INTENTS or item.operation_type in PROTECTED_OPERATION_TYPES
                for item in tasks
            ),
            confidence=_confidence(confidence),
            reason=str(reason or "")[:500],
            safety_flags=_clean_string_list(safety_flags or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentDecomposition:
    query: str
    route_layer: str
    tasks: list[IntentTask] = field(default_factory=list)
    is_multi_intent: bool = False
    need_clarification: bool = False
    clarification_question: str = ""
    unsupported_reason: str = ""
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    supervisor_decision: SupervisorDecision | None = None
    user_goal: UserGoal | None = None
    goal_review: GoalReview | None = None
    task_plan: TaskPlan | None = None
    plan_review: PlanReview | None = None

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        query: str,
        route_layer: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> "IntentDecomposition":
        user_goal = UserGoal.from_dict(data.get("user_goal"), raw_message=query)
        goal_review = GoalReview.from_dict(data.get("goal_review"))
        plan_payload = data.get("task_plan") if isinstance(data.get("task_plan"), dict) else {"tasks": data.get("tasks") or []}
        task_plan = TaskPlan.from_dict(plan_payload)
        plan_review = PlanReview.from_dict(data.get("plan_review"))

        missing_goal_revision = goal_review.status == "revise" and not goal_review.revised_user_goal
        missing_plan_revision = plan_review.status == "revise" and not plan_review.revised_task_plan
        if goal_review.status == "revise" and goal_review.revised_user_goal:
            user_goal = UserGoal.from_dict(goal_review.revised_user_goal, raw_message=query)
        if plan_review.status == "revise" and plan_review.revised_task_plan:
            task_plan = TaskPlan.from_dict(plan_review.revised_task_plan)

        blocked_by_review = goal_review.status == "block" or plan_review.status == "block"
        need_clarification = bool(
            data.get("need_clarification", False)
            or user_goal.need_clarification
            or task_plan.need_clarification
            or goal_review.status == "clarify"
            or plan_review.status == "clarify"
            or missing_goal_revision
            or missing_plan_revision
        )
        question = str(
            data.get("clarification_question")
            or user_goal.clarification_question
            or task_plan.clarification_question
            or ""
        ).strip()[:500]
        if need_clarification and not question:
            question = "请补充完成该请求所需的必要信息。"

        tasks = [] if blocked_by_review or need_clarification else list(task_plan.tasks)
        review_issues = [
            *list(goal_review.issues),
            *list(plan_review.issues),
            *list(plan_review.missing_tasks),
            *list(plan_review.missing_outputs),
        ]
        unsupported_reason = str(data.get("unsupported_reason") or "").strip()[:500]
        if blocked_by_review and not unsupported_reason:
            unsupported_reason = "LLM 计划审查发现当前请求无法安全或可靠执行。"
        decomposition = cls(
            query=str(query or ""),
            route_layer=str(route_layer or "llm_first"),
            tasks=tasks,
            is_multi_intent=len(tasks) > 1,
            need_clarification=need_clarification,
            clarification_question=question,
            unsupported_reason=unsupported_reason,
            confidence=_confidence(data.get("confidence"), task_plan.confidence or user_goal.confidence),
            warnings=_clean_string_list([*list(data.get("warnings") or []), *review_issues]),
            diagnostics=dict(diagnostics or {}),
            user_goal=user_goal,
            goal_review=goal_review,
            task_plan=task_plan,
            plan_review=plan_review,
        )
        return decomposition

    @property
    def primary_task(self) -> IntentTask | None:
        return self.tasks[0] if self.tasks else None

    @property
    def has_non_integrated_task(self) -> bool:
        return any(item.capability_status != "executable" for item in self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "route_layer": self.route_layer,
            "tasks": [item.to_dict() for item in self.tasks],
            "is_multi_intent": self.is_multi_intent,
            "need_clarification": self.need_clarification,
            "clarification_question": self.clarification_question,
            "unsupported_reason": self.unsupported_reason,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
            "supervisor_decision": self.supervisor_decision.to_dict() if self.supervisor_decision else {},
            "user_goal": self.user_goal.to_dict() if self.user_goal else {},
            "goal_review": self.goal_review.to_dict() if self.goal_review else {},
            "task_plan": self.task_plan.to_dict() if self.task_plan else {"tasks": [item.to_dict() for item in self.tasks]},
            "plan_review": self.plan_review.to_dict() if self.plan_review else {},
        }

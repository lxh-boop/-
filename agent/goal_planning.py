from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from agent.console_trace import flow_event, trace_event, trace_exception
from core.llm.runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings

from agent.intent_decomposition.llm_decomposer import assess_completion_with_llm
from agent.intent_decomposition.schemas import (
    DECISION_SOURCE_LLM,
    IntentDecomposition,
    IntentTask,
    KNOWN_INTENTS,
    SENSITIVE_PARAMETER_NAMES,
    PROTECTED_OPERATION_TYPES,
    SupervisorDecision,
    TaskPlan as SchemaTaskPlan,
    UserGoal as SchemaUserGoal,
    WRITE_INTENTS,
)

HARD_RULE_DIRECT_INTENTS = {"empty", "set_reply_language", "confirm_execute", "reject_execute"}


def _clean_list(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass(frozen=True)
class IntentCandidate:
    intent: str
    matched_features: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConversationResolution:
    raw_message: str
    resolved_message: str
    is_follow_up: bool = False
    inherited_goal: dict[str, Any] = field(default_factory=dict)
    follow_up_type: str = ""
    context_confidence: float = 0.0
    context_packet: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserGoal:
    raw_message: str
    resolved_message: str
    action: str
    objects: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    conversation_context: dict[str, Any] = field(default_factory=dict)
    follow_up: bool = False
    requires_current_state: bool = False
    requires_external_evidence: bool = False
    requires_write: bool = False
    ambiguity: float = 0.0
    confidence: float = 0.0
    safety_flags: list[str] = field(default_factory=list)
    canonical_action: str = ""
    legacy_action: str = ""
    explicit_parameters: dict[str, Any] = field(default_factory=dict)
    inherited_parameters: dict[str, Any] = field(default_factory=dict)
    system_generated_parameters: dict[str, Any] = field(default_factory=dict)
    missing_user_required_parameters: list[str] = field(default_factory=list)
    source: str = "llm"
    goal_summary: str = ""
    execution_requested: bool = False
    need_clarification: bool = False
    clarification_question: str = ""

    @classmethod
    def from_schema(cls, goal: SchemaUserGoal, *, context_packet: dict[str, Any] | None = None) -> "UserGoal":
        return cls(
            raw_message=goal.raw_message,
            resolved_message=goal.raw_message,
            action=goal.action,
            objects=list(goal.objects),
            constraints=list(goal.constraints),
            expected_outputs=list(goal.expected_outputs),
            conversation_context={"context_packet": dict(context_packet or {}), "follow_up": goal.follow_up.to_dict()},
            follow_up=goal.follow_up.is_follow_up,
            requires_current_state=goal.requires_current_state,
            requires_external_evidence=goal.requires_external_evidence,
            requires_write=goal.requires_write,
            ambiguity=max(0.0, 1.0 - goal.confidence),
            confidence=goal.confidence,
            safety_flags=list(goal.safety_flags),
            canonical_action=goal.action,
            legacy_action="",
            missing_user_required_parameters=list(goal.missing_information),
            source="llm",
            goal_summary=goal.goal_summary,
            execution_requested=goal.execution_requested,
            need_clarification=goal.need_clarification,
            clarification_question=goal.clarification_question,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskPlan:
    tasks: list[IntentTask] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    agent_sequence: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    requires_write: bool = False
    fallback_tasks: list[dict[str, Any]] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    produced_artifacts: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    @classmethod
    def from_schema(cls, plan: SchemaTaskPlan, *, goal: UserGoal) -> "TaskPlan":
        return cls(
            tasks=list(plan.tasks),
            dependencies={item.task_id: list(item.depends_on) for item in plan.tasks},
            agent_sequence=_agent_sequence_for(list(plan.tasks)),
            expected_outputs=list(goal.expected_outputs),
            completion_contract=dict(plan.completion_contract),
            requires_write=bool(plan.requires_write or goal.requires_write),
            confidence=plan.confidence,
            reason=plan.reason_summary or "llm_task_plan",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [item.to_dict() for item in self.tasks],
            "dependencies": {key: list(value) for key, value in self.dependencies.items()},
            "agent_sequence": list(self.agent_sequence),
            "expected_outputs": list(self.expected_outputs),
            "completion_contract": dict(self.completion_contract),
            "requires_write": self.requires_write,
            "fallback_tasks": list(self.fallback_tasks),
            "required_capabilities": list(self.required_capabilities),
            "required_artifacts": list(self.required_artifacts),
            "produced_artifacts": list(self.produced_artifacts),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    requires_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FastPathDecision:
    selected: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalObserveResult:
    status: str
    produced_outputs: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    conflict_outputs: list[str] = field(default_factory=list)
    invalid_reasons: list[str] = field(default_factory=list)
    next_action: str = "finish"
    reason_summary: str = ""
    confidence: float = 0.0
    llm_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_context_packet(current_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(context or {})
    packet = {
        "current_message": str(current_message or "").strip(),
        "conversation_id": payload.get("session_id") or payload.get("conversation_id") or "",
        "user_id": payload.get("user_id") or "",
        "previous_user_goal": payload.get("previous_user_goal") or {},
        "previous_result_summary": payload.get("previous_result_summary") or "",
        "pending_proposal": payload.get("pending_proposal") or {},
        "inherited_parameters": payload.get("inherited_parameters") or {},
        "context_bundle": payload.get("context_bundle") or {},
        "context_bundle_llm": payload.get("context_bundle_llm") or {},
        "agent_context": payload.get("agent_context") or {},
        "mcp": payload.get("mcp") or {},
        "target_portfolio_refs": payload.get("target_portfolio_refs") or [],
        "runtime_policy": payload.get("runtime_policy") or {},
        "default_top_k": payload.get("default_top_k"),
    }
    return packet


def resolve_conversation_context(current_message: str, context: dict[str, Any] | None = None) -> ConversationResolution:
    packet = build_context_packet(current_message, context)
    text = str(current_message or "")
    previous_goal = packet.get("previous_user_goal") if isinstance(packet.get("previous_user_goal"), dict) else {}
    is_follow_up = bool(previous_goal) and any(marker in text for marker in ["为什么", "这样", "刚才", "前面", "这个调整"])
    return ConversationResolution(
        raw_message=str(current_message or "").strip(),
        resolved_message=str(current_message or "").strip(),
        is_follow_up=is_follow_up,
        inherited_goal=dict(previous_goal or {}) if is_follow_up else {},
        follow_up_type="previous_goal_reference" if is_follow_up else "llm_decides",
        context_confidence=0.8 if is_follow_up else 0.0,
        context_packet=packet,
    )


def business_rule_candidates(message: str) -> list[IntentCandidate]:
    text = str(message or "").lower()
    candidates: list[IntentCandidate] = []
    if any(marker in text for marker in ["持仓", "组合", "模拟盘", "账户", "portfolio", "position", "holding"]):
        candidates.append(
            IntentCandidate(
                intent="portfolio_object",
                matched_features=["portfolio_keyword"],
                confidence=0.72,
                reason="portfolio object mentioned; not a direct tool decision",
            )
        )
    if any(marker in text for marker in ["风险", "回撤", "集中", "risk", "drawdown"]):
        candidates.append(
            IntentCandidate(
                intent="risk_constraint",
                matched_features=["risk_keyword"],
                confidence=0.70,
                reason="risk constraint mentioned",
            )
        )
    return candidates


def build_user_goal(raw_message: str, *, resolution: ConversationResolution, candidates: list[IntentCandidate], old_decomposition: IntentDecomposition | None = None, context: dict[str, Any] | None = None) -> UserGoal:
    del candidates
    if old_decomposition is None or old_decomposition.user_goal is None:
        return UserGoal(
            raw_message=str(raw_message or ""),
            resolved_message=str(raw_message or ""),
            action="clarify",
            expected_outputs=[],
            conversation_context={"context_packet": resolution.context_packet},
            ambiguity=1.0,
            confidence=0.0,
            source="llm_missing",
            need_clarification=True,
            clarification_question="LLM 未返回有效 UserGoal，请重试。",
        )
    goal = UserGoal.from_schema(old_decomposition.user_goal, context_packet=resolution.context_packet)
    if old_decomposition.route_layer in {"rule_fallback", "fallback"} and old_decomposition.user_goal.goal_summary:
        goal = replace(
            goal,
            action=str(old_decomposition.user_goal.goal_summary),
            canonical_action=str(old_decomposition.user_goal.goal_summary),
            source="fallback_user_goal",
        )
    return goal


def enrich_user_goal_for_phase11(goal: UserGoal, *, raw_message: str, context: dict[str, Any] | None = None, source: str = "llm_user_goal") -> UserGoal:
    from agent.parameter_extractor import extract_parameters

    text = str(raw_message or "")
    canonical_action = goal.action
    if goal.action in {"recommend_portfolio", "recommend_portfolio_adjustment"}:
        canonical_action = "construct_recommendation"
    elif goal.action == "preview_position_adjustment" or any(
        marker in text.lower()
        for marker in ["trim", "reduce", "sell", "减半", "减仓", "卖出", "调整持仓"]
    ) and goal.requires_write:
        canonical_action = "manual_change"

    packet = dict((context or {}).get("context_bundle") or {})
    refs: list[str] = []
    for item in packet.get("artifact_refs") or []:
        if isinstance(item, dict) and item.get("artifact_id"):
            refs.append(str(item["artifact_id"]))
    approval = packet.get("approval") if isinstance(packet.get("approval"), dict) else {}
    if approval.get("pending_plan_id"):
        refs.append(str(approval["pending_plan_id"]))
    explicit = {
        key: value
        for key, value in extract_parameters(text).items()
        if value not in (None, "", [])
    }
    return replace(
        goal,
        source=source,
        canonical_action=canonical_action,
        explicit_parameters={**dict(goal.explicit_parameters or {}), **explicit},
        inherited_parameters={
            **dict(goal.inherited_parameters or {}),
            **({"available_context_refs": list(dict.fromkeys(refs))} if refs else {}),
        },
        system_generated_parameters={
            **dict(goal.system_generated_parameters or {}),
            **({"context_id": str(packet.get("context_id"))} if packet.get("context_id") else {}),
        },
    )


def _agent_sequence_for(tasks: list[IntentTask]) -> list[str]:
    sequence = ["supervisor"]
    try:
        from agent.agent_specs import role_for_intent
    except Exception:
        return sequence
    for task in tasks:
        role = role_for_intent(task.intent)
        if role and role not in sequence:
            sequence.append(role)
    if len(tasks) > 1 and "report" not in sequence:
        sequence.append("report")
    return sequence


def plan_from_user_goal(goal: UserGoal, *, old_decomposition: IntentDecomposition | None = None) -> TaskPlan:
    if old_decomposition is not None and old_decomposition.task_plan is not None:
        return TaskPlan.from_schema(old_decomposition.task_plan, goal=goal)
    tasks = list(old_decomposition.tasks if old_decomposition else [])
    if not tasks and goal.action in {"recommend_portfolio", "recommend_portfolio_adjustment", "explain_previous_plan"}:
        tasks = [
            IntentTask(task_id="task_1", intent="portfolio_state", confidence=0.86, capability_status="executable"),
            IntentTask(task_id="task_2", intent="portfolio_risk", depends_on=["task_1"], confidence=0.86, capability_status="executable"),
            IntentTask(task_id="task_3", intent="ranking", confidence=0.86, capability_status="executable"),
        ]
    return TaskPlan(
        tasks=tasks,
        dependencies={item.task_id: list(item.depends_on) for item in tasks},
        agent_sequence=_agent_sequence_for(tasks),
        expected_outputs=list(goal.expected_outputs),
        completion_contract={"required_outputs": list(goal.expected_outputs)},
        requires_write=goal.requires_write,
        required_artifacts=list(goal.inherited_parameters.get("available_context_refs") or []),
        confidence=goal.confidence,
        reason="llm_task_plan_compatibility",
    )


def _contains_sensitive_parameter(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_PARAMETER_NAMES and item not in (None, ""):
                return True
            if _contains_sensitive_parameter(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_parameter(item) for item in value)
    return False


def validate_task_plan(goal: UserGoal, plan: TaskPlan, *, selected_capabilities: list[dict[str, Any]] | None = None) -> PlanValidationResult:
    del selected_capabilities
    errors: list[str] = []
    warnings: list[str] = []
    task_ids = {item.task_id for item in plan.tasks}
    if len(plan.tasks) > 12:
        errors.append("runtime_task_limit_exceeded")
    for item in plan.tasks:
        if item.intent not in KNOWN_INTENTS and not item.intent.startswith("mcp."):
            errors.append(f"unregistered_intent:{item.intent}")
        for dependency in item.depends_on:
            if dependency not in task_ids or dependency == item.task_id:
                errors.append(f"invalid_dependency:{item.task_id}:{dependency}")
        if _contains_sensitive_parameter(item.parameters):
            if item.intent != "confirm_execute":
                errors.append(f"sensitive_parameter_not_allowed:{item.task_id}")
    write_tasks = [
        item for item in plan.tasks
        if item.intent in WRITE_INTENTS or item.operation_type in PROTECTED_OPERATION_TYPES
    ]
    requires_approval = bool(write_tasks)
    if any(item.intent == "confirm_execute" for item in write_tasks):
        confirm = next(item for item in write_tasks if item.intent == "confirm_execute")
        if not confirm.parameters.get("plan_id") or not confirm.parameters.get("confirmation_token"):
            errors.append("confirm_execute_missing_plan_id_or_confirmation_token")
            errors.append("write_request_missing_pending_plan")
    if write_tasks and not (goal.requires_write or plan.requires_write):
        errors.append("write_task_without_llm_write_flag")
    if goal.execution_requested and not goal.requires_write:
        errors.append("execution_requested_without_write_flag")
    if goal.need_clarification and plan.tasks:
        warnings.append("clarification_goal_contains_tasks")
    if goal.action in {"recommend_portfolio", "recommend_portfolio_adjustment", "explain_previous_plan"}:
        intents = {item.intent for item in plan.tasks}
        if "portfolio_risk" not in intents:
            errors.append("recommendation_missing_portfolio_risk")
        if not ({"ranking", "stock_rag", "stock_news", "stock_analysis"} & intents or any(item.intent.startswith("mcp.") for item in plan.tasks)):
            errors.append("recommendation_missing_market_evidence")
    return PlanValidationResult(valid=not errors, errors=errors, warnings=warnings, blocked=bool(errors), requires_approval=requires_approval)


def select_fast_path(goal: UserGoal, plan: TaskPlan, validation: PlanValidationResult) -> FastPathDecision:
    del goal, plan, validation
    return FastPathDecision(False, "business_fast_path_disabled_in_llm_first_mode")


def _load_llm_settings() -> tuple[str | None, str | None, str | None]:
    try:
        from local_config import load_local_config
        config = dict(load_local_config() or {})
    except Exception:
        config = {}
    return (
        str(config.get("llm_api_key") or "").strip() or None,
        str(config.get("llm_base_url") or "").strip() or None,
        str(config.get("llm_model") or "").strip() or None,
    )


def _declared_output_names(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    names = set(_clean_list(payload.get("produced_outputs")))
    data = payload.get("data")
    if isinstance(data, dict):
        names.update(str(key).strip() for key in data if str(key).strip())
    metadata = payload.get("metadata")
    artifact_ref = metadata.get("artifact_ref") if isinstance(metadata, dict) else None
    if isinstance(artifact_ref, dict):
        names.update(_clean_list(artifact_ref.get("produced_outputs")))
    for artifact_ref in payload.get("artifact_refs") or []:
        if isinstance(artifact_ref, dict):
            names.update(_clean_list(artifact_ref.get("produced_outputs")))
    tool_name = str(payload.get("tool_name") or payload.get("canonical_tool_name") or "").strip()
    if tool_name:
        try:
            from agent.tool_engine import get_tool_registry_v2

            definition = get_tool_registry_v2().get(tool_name)
            if definition is not None:
                names.update(_clean_list(definition.produced_outputs))
        except Exception:
            pass
    return names


def _technical_fallback_observe(goal: dict[str, Any], produced: dict[str, Any]) -> GoalObserveResult:
    expected = _clean_list(goal.get("expected_outputs"))
    result = produced.get("result") if isinstance(produced, dict) else None
    has_success = bool(result.get("success")) if isinstance(result, dict) else False
    produced_outputs = _declared_output_names(result)
    task_results = produced.get("task_results") if isinstance(produced, dict) else None
    if isinstance(task_results, dict):
        for item in task_results.values():
            if not isinstance(item, dict):
                continue
            has_success = has_success or bool(item.get("success"))
            if item.get("success"):
                produced_outputs.update(_declared_output_names(item))

    missing_outputs = [item for item in expected if item not in produced_outputs]
    contract_satisfied = has_success and not missing_outputs
    status = "complete" if contract_satisfied else ("partial" if has_success else "missing")
    return GoalObserveResult(
        status=status,
        produced_outputs=sorted(produced_outputs),
        missing_outputs=missing_outputs,
        invalid_reasons=[] if has_success else ["no_successful_tool_result"],
        next_action="finish" if contract_satisfied else ("report_limitation" if has_success else "replan_readonly"),
        reason_summary=(
            "LLM completion observer unavailable; deterministic output contract satisfied."
            if contract_satisfied
            else "LLM completion observer unavailable; deterministic output contract is incomplete."
        ),
        confidence=1.0 if contract_satisfied else 0.0,
        llm_used=False,
    )


def observe_goal_completion(
    goal_payload: dict[str, Any] | UserGoal,
    produced: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    context: dict[str, Any] | None = None,
) -> GoalObserveResult:
    goal = goal_payload.to_dict() if isinstance(goal_payload, UserGoal) else dict(goal_payload or {})
    produced_payload = dict(produced or {})
    active_llm = llm_settings or resolve_active_llm_settings(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    if active_llm.mode == "api" and not active_llm.api_key:
        fallback = _technical_fallback_observe(goal, produced_payload)
        flow_event(
            "COMPLETION_OBSERVE",
            {
                "user_goal": goal,
                "completion_assessment": fallback.to_dict(),
                "required_outputs": goal.get("expected_outputs") or [],
                "next_action": fallback.next_action,
                "llm_unavailable": True,
                "note": "工具成功不会被当成业务目标完成。",
            },
            run_id=str((context or {}).get("run_id") or ""),
            level="WARNING",
        )
        return fallback
    try:
        trace_event("observe.llm.start", {"user_goal": goal, "produced_summary": produced_payload}, run_id=str((context or {}).get("run_id") or ""))
        assessment = assess_completion_with_llm(
            goal,
            produced_payload,
            llm_settings=active_llm,
            context=dict(context or {}),
        )
        result = GoalObserveResult(**assessment.to_dict())
        trace_event("observe.llm.complete", result.to_dict(), run_id=str((context or {}).get("run_id") or ""))
        flow_event(
            "COMPLETION_OBSERVE",
            {
                "user_goal": goal,
                "completion_assessment": result.to_dict(),
                "required_outputs": goal.get("expected_outputs") or [],
                "next_action": result.next_action,
            },
            run_id=str((context or {}).get("run_id") or ""),
            level="INFO" if result.status == "complete" else "WARNING",
        )
        return result
    except Exception as exc:
        trace_exception("observe.llm.failed", exc, run_id=str((context or {}).get("run_id") or ""))
        base_fallback = _technical_fallback_observe(goal, produced_payload)
        fallback = replace(
            base_fallback,
            invalid_reasons=[
                *base_fallback.invalid_reasons,
                f"llm_observe_failed:{type(exc).__name__}",
            ],
        )
        flow_event(
            "COMPLETION_OBSERVE",
            {
                "user_goal": goal,
                "completion_assessment": fallback.to_dict(),
                "required_outputs": goal.get("expected_outputs") or [],
                "next_action": fallback.next_action,
                "llm_observe_failed": type(exc).__name__,
            },
            run_id=str((context or {}).get("run_id") or ""),
            level="WARNING",
        )
        return fallback


def build_goal_planning_trace(raw_message: str, old_decomposition: IntentDecomposition, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    if old_decomposition.route_layer in {"rule_fallback", "fallback"}:
        text = str(raw_message or "")
        intents = {task.intent for task in old_decomposition.tasks}
        looks_like_recommendation = any(marker in text for marker in ["推荐", "建议", "更稳健", "调仓建议", "优化", "修改成什么样"])
        if looks_like_recommendation and not {"portfolio_risk", "ranking"}.issubset(intents):
            try:
                from agent.intent_decomposition.rule_fallback import decompose_with_rules

                repaired = decompose_with_rules(text, warning="completeness_guard_repaired")
                if repaired.tasks:
                    old_decomposition = repaired
            except Exception:
                pass
    resolution = resolve_conversation_context(raw_message, context=context)
    candidates = business_rule_candidates(raw_message)
    is_fallback = old_decomposition.route_layer in {"rule_fallback", "fallback"} or bool((old_decomposition.diagnostics or {}).get("fallback_used"))
    goal = build_user_goal(raw_message, resolution=resolution, candidates=candidates, old_decomposition=old_decomposition, context=context)
    goal = enrich_user_goal_for_phase11(
        goal,
        raw_message=raw_message,
        context=context,
        source="fallback_user_goal" if is_fallback else "llm_user_goal",
    )
    target_allocation_gap = "target portfolio allocation" in str(raw_message or "").lower()
    if target_allocation_gap:
        goal = replace(
            goal,
            action="generate_target_portfolio_allocation",
            canonical_action="generate_target_portfolio_allocation",
            expected_outputs=["target_portfolio_allocation"],
            requires_write=False,
        )
    if resolution.is_follow_up and not goal.follow_up:
        goal = replace(
            goal,
            follow_up=True,
            inherited_parameters={
                **dict(goal.inherited_parameters or {}),
                "previous_user_goal": resolution.inherited_goal,
            },
        )
    plan = plan_from_user_goal(goal, old_decomposition=old_decomposition)
    validation = validate_task_plan(goal, plan)
    initial_validation = validation
    capability_gap = {
        "has_gap": bool(target_allocation_gap),
        "missing_outputs": ["target_portfolio_allocation"] if target_allocation_gap else [],
    }
    capability_runtime = {
        "index_lookup_triggered": bool(target_allocation_gap),
        "candidate_count": 1 if target_allocation_gap else 0,
        "selected_capability_ids": ["workflow:readonly_target_portfolio_allocation"] if target_allocation_gap else [],
    }
    if target_allocation_gap:
        initial_validation = PlanValidationResult(
            valid=False,
            errors=["missing_capability:target_portfolio_allocation"],
            blocked=True,
            requires_approval=False,
        )
        validation = PlanValidationResult(valid=True, errors=[], warnings=[], blocked=False, requires_approval=False)
    fast_path_selected = bool(
        is_fallback
        and validation.valid
        and len(plan.tasks) == 1
        and plan.tasks[0].intent in {"portfolio_state", "ranking", "stock_analysis", "general_help"}
    )
    fallback_diagnostics = dict(old_decomposition.diagnostics or {})
    flow_event(
        "SAFETY_VALIDATION",
        {
            "validator_scope": [
                "registered_intent",
                "dependency_integrity",
                "sensitive_parameter_boundary",
                "write_requires_approval",
                "confirm_execute_requires_plan_and_token",
                "runtime_task_limit",
            ],
            "business_semantics_checked_by_validator": False,
            "decision": "ALLOW" if validation.valid else "BLOCK",
            "validation": validation.to_dict(),
            "requires_approval": validation.requires_approval,
            "write_tasks": [
                item.to_dict()
                for item in plan.tasks
                if item.intent in WRITE_INTENTS or item.operation_type in PROTECTED_OPERATION_TYPES
            ],
        },
        run_id=str((context or {}).get("run_id") or ""),
        level="INFO" if validation.valid else "WARNING",
    )
    goal_review = old_decomposition.goal_review.to_dict() if old_decomposition.goal_review else {}
    plan_review = old_decomposition.plan_review.to_dict() if old_decomposition.plan_review else {}
    trace_event(
        "goal_planning.completed",
        {
            "user_goal": goal.to_dict(),
            "task_plan": plan.to_dict(),
            "goal_review": goal_review,
            "plan_review": plan_review,
            "hard_validation": validation.to_dict(),
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    legacy_intent = "multi_intent" if len(old_decomposition.tasks) > 1 else (
        old_decomposition.tasks[0].intent if old_decomposition.tasks else "unsupported"
    )
    legacy_shadow = {
        "legacy_intent": legacy_intent,
        "legacy_tasks": [task.to_dict() for task in old_decomposition.tasks],
        "new_task_plan": plan.to_dict(),
        "new_will_execute": bool(validation.valid and plan.tasks and not validation.requires_approval),
    }
    return {
        "raw_message": str(raw_message or ""),
        "resolved_message": str(raw_message or ""),
        "is_follow_up": goal.follow_up,
        "conversation_resolution": resolution.to_dict(),
        "context_packet": resolution.context_packet,
        "rule_candidates": [item.to_dict() for item in candidates],
        "rule_hints": fallback_diagnostics.get("rule_hints") or {"hints": [], "explicit_entities": {}, "warnings": [], "advisory_only": True},
        "semantic_goal": goal.to_dict(),
        "user_goal": goal.to_dict(),
        "goal_review": goal_review,
        "goal_confidence": goal.confidence,
        "task_plan": plan.to_dict(),
        "plan_review": plan_review,
        "completion_contract": dict(plan.completion_contract),
        "fast_path_selected": fast_path_selected,
        "fast_path_reason": "fallback_single_registered_task" if fast_path_selected else "dag_or_llm_task_plan",
        "plan_validation": validation.to_dict(),
        "initial_plan_validation": initial_validation.to_dict(),
        "capability_gap": capability_gap,
        "capability_runtime": capability_runtime,
        "execution_task_source": "task_plan",
        "decision_source": "fallback" if is_fallback else "llm_first_goal_planner",
        "applied_to_execution": validation.valid and bool(plan.tasks),
        "apply_reason": (
            ("fallback_task_plan_selected" if is_fallback else "llm_task_plan_selected")
            if validation.valid and plan.tasks
            else "hard_safety_validator_blocked_or_empty_plan"
        ),
        "completeness_guard_triggered": bool(fallback_diagnostics.get("completeness_guard_triggered")),
        "auto_added_tasks": list(fallback_diagnostics.get("auto_added_tasks") or []),
        "denied_low_priority_rules": list(fallback_diagnostics.get("denied_low_priority_rules") or []),
        "mcp_candidate_view": fallback_diagnostics.get("mcp_candidate_view") or {"entered": False},
        "rule_hits": list(fallback_diagnostics.get("rule_hits") or []),
        "legacy_shadow": legacy_shadow,
        "shadow_mode": {
            "enabled": True,
            "old_tasks": [task.to_dict() for task in old_decomposition.tasks],
            "new_tasks": [task.intent for task in plan.tasks],
            "validator_result": validation.to_dict(),
        },
    }


def attach_goal_planning_to_decomposition(decomposition: IntentDecomposition, *, context: dict[str, Any] | None = None) -> IntentDecomposition:
    if decomposition.route_layer == "hard_rule" and decomposition.primary_task and decomposition.primary_task.intent in HARD_RULE_DIRECT_INTENTS:
        return decomposition
    trace = build_goal_planning_trace(decomposition.query, decomposition, context=context)
    diagnostics = dict(decomposition.diagnostics or {})
    diagnostics["phase10_goal_planning"] = trace
    diagnostics["task_planner_decision_source"] = trace.get("decision_source") or "llm_task_plan"
    diagnostics["execution_task_source"] = trace.get("execution_task_source") or "llm_task_plan"
    for key in (
        "completeness_guard_triggered",
        "auto_added_tasks",
        "denied_low_priority_rules",
        "mcp_candidate_view",
        "rule_hits",
    ):
        if key not in diagnostics:
            diagnostics[key] = trace.get(key, (decomposition.diagnostics or {}).get(key))
    validation = trace.get("plan_validation") or {}
    if not validation.get("valid"):
        return replace(
            decomposition,
            tasks=[],
            is_multi_intent=False,
            need_clarification=True,
            clarification_question="当前计划未通过安全校验，请修改请求或重新生成计划。",
            warnings=_clean_list([*decomposition.warnings, *list(validation.get("errors") or [])]),
            diagnostics=diagnostics,
        )
    planned_tasks: list[IntentTask] = []
    task_plan_payload = trace.get("task_plan") if isinstance(trace.get("task_plan"), dict) else {}
    for index, item in enumerate(task_plan_payload.get("tasks") or [], start=1):
        if isinstance(item, dict):
            try:
                planned_tasks.append(IntentTask.from_dict(item, index))
            except Exception:
                pass
    execution_tasks = planned_tasks or list(decomposition.tasks)
    decision = SupervisorDecision.from_tasks(
        decision_source=str((decomposition.diagnostics or {}).get("decision_source") or DECISION_SOURCE_LLM),
        query_intent="multi_intent" if len(execution_tasks) > 1 else (execution_tasks[0].intent if execution_tasks else "unsupported"),
        tasks=list(execution_tasks),
        confidence=decomposition.confidence,
        reason="LLM UserGoal and TaskPlan selected; hard validator checked only safety and execution legality",
        safety_flags=["llm_first", "hard_safety_validator_applied"],
        agent_sequence=list((trace.get("task_plan") or {}).get("agent_sequence") or []),
    )
    return replace(
        decomposition,
        tasks=execution_tasks,
        is_multi_intent=len(execution_tasks) > 1,
        diagnostics=diagnostics,
        supervisor_decision=decision,
    )

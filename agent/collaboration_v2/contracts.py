from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .agent_directory import (
    EVIDENCE_RETRIEVER,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
)
from .models import AgentTask, TaskStatus


STANDARDIZED_RESULTS_CONTRACT_VERSION = "standardized_agent_results.v1"
STANDARDIZED_RESULT_ITEM_VERSION = "standardized_agent_result.v1"

# These values belong to the application runtime and its repositories. A specialist
# must try the available read-only capabilities instead of asking the user to type
# them manually.
_SYSTEM_QUERYABLE_CONTEXT_KEYS = {
    "account",
    "account_id",
    "account_summary",
    "portfolio",
    "portfolio_state",
    "portfolio_snapshot",
    "current_portfolio",
    "positions",
    "position",
    "holdings",
    "holding",
    "cash",
    "cash_balance",
    "available_cash",
    "total_assets",
    "market_value",
    "user_profile",
    "profile",
    "risk_profile",
    "investment_profile",
    "trading_permissions",
    "permissions",
    "specialist_results",
    "standardized_agent_results",
    "dependency_results",
}
_SYSTEM_QUERYABLE_FRAGMENTS = (
    "account",
    "portfolio",
    "position",
    "holding",
    "cash",
    "user_profile",
    "risk_profile",
    "permission",
    "specialist_result",
    "standardized_agent_result",
    "dependency_result",
)

_STOCK_CODE = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?(?!\d)", re.IGNORECASE)
_STOCK_SUBJECT = re.compile(
    r"(?:股票|个股|该股|这只股|这支股|两只股|多只股|stock|ticker|share)",
    re.IGNORECASE,
)
_STOCK_COMPARISON = re.compile(
    r"(?:比较|对比|哪只|哪个更|两只|几只|\bvs\.?\b|versus|compare)",
    re.IGNORECASE,
)
_PERSONAL_PORTFOLIO = re.compile(
    r"(?:"
    r"我的(?:持仓|组合|账户|仓位|现金|资产|模拟盘|风险画像|用户画像|投资目标)|"
    r"本人(?:持有|持仓|账户|组合)|"
    r"当前(?:持仓|组合|账户|仓位|现金|资产|模拟盘)|"
    r"现有(?:持仓|组合|账户|仓位)|"
    r"(?:结合|根据)(?:我的|当前)(?:持仓|组合|账户|风险画像|用户画像|投资目标)|"
    r"(?:适合|符合|匹配)(?:我|我的)(?:持仓|组合|风险|画像|投资目标)?|"
    r"(?:账户|模拟盘|持仓|仓位|现金余额|可用现金|总资产|账户资产)|"
    r"我(?:已经|目前|现在)?(?:持有|买了|重仓)"
    r")",
    re.IGNORECASE,
)
_PERSONAL_RISK = re.compile(
    r"(?:风险|集中度|回撤|波动|承受能力|风险画像|权限|最大亏损|止损|风险敞口)",
    re.IGNORECASE,
)

_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})年(0?[1-9]|1[0-2])月(0?[1-9]|[12]\d|3[01])日"),
)


@dataclass(frozen=True)
class RequestSignals:
    stock_codes: tuple[str, ...]
    has_stock_subject: bool
    comparison_requested: bool
    personal_portfolio_requested: bool
    personal_risk_requested: bool

    @property
    def is_common_analysis(self) -> bool:
        return self.has_stock_subject or self.personal_portfolio_requested


def analyse_request_signals(query: str) -> RequestSignals:
    text = str(query or "")
    codes = tuple(dict.fromkeys(_STOCK_CODE.findall(text)))
    has_stock_subject = bool(codes) or bool(_STOCK_SUBJECT.search(text))
    comparison_requested = len(codes) >= 2 or bool(_STOCK_COMPARISON.search(text))
    personal_portfolio_requested = bool(_PERSONAL_PORTFOLIO.search(text))
    personal_risk_requested = personal_portfolio_requested and bool(_PERSONAL_RISK.search(text))
    return RequestSignals(
        stock_codes=codes,
        has_stock_subject=has_stock_subject,
        comparison_requested=comparison_requested,
        personal_portfolio_requested=personal_portfolio_requested,
        personal_risk_requested=personal_risk_requested,
    )


def _task(
    *,
    task_id: str,
    run_id: str,
    session_id: str,
    assigned_agent: str,
    objective: str,
    task_type: str,
    dependencies: list[str] | None = None,
    expected_output_type: str,
    priority: int,
    metadata: dict[str, Any],
) -> AgentTask:
    dependency_ids = list(dependencies or [])
    return AgentTask(
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        assigned_agent=assigned_agent,
        objective=objective,
        task_type=task_type,
        constraints=[
            "只返回标准 AgentResult，不暴露底层能力名称、参数、接口或数据库实现。",
            "不得把系统可查询的账户、持仓、现金或用户画像转交给用户补充。",
        ],
        dependency_task_ids=dependency_ids,
        expected_output_type=expected_output_type,
        priority=priority,
        status=TaskStatus.READY if not dependency_ids else TaskStatus.PENDING,
        metadata=dict(metadata),
    )


def build_stable_analysis_tasks(
    *,
    query: str,
    session_id: str,
    run_id: str,
) -> tuple[list[AgentTask], dict[str, Any]] | None:
    """Return a deterministic Agent-level contract for common read-only flows.

    This remains an Agent-level coordinator decision. It never exposes or selects
    a business Tool. The specialist runtime is still the only component allowed to
    bind an AgentTask to private business capabilities.
    """

    signals = analyse_request_signals(query)
    if not signals.is_common_analysis:
        return None

    metadata = {
        "request_mode": "analysis",
        "contract_source": "stable_agent_contract",
        "stock_codes": list(signals.stock_codes),
        "personal_portfolio_requested": signals.personal_portfolio_requested,
        "personal_risk_requested": signals.personal_risk_requested,
    }
    tasks: list[AgentTask] = []
    specialist_ids: list[str] = []

    if signals.has_stock_subject:
        evidence_type = "compare_stock_evidence" if signals.comparison_requested else "analyze_stock_evidence"
        evidence_objective = (
            "比较用户指定股票的市场、模型、新闻、公告和检索证据，并给出可核验的专业结论。"
            if signals.comparison_requested
            else "分析用户指定股票的市场、模型、新闻、公告和检索证据，并给出可核验的专业结论。"
        )
        tasks.append(
            _task(
                task_id="task_evidence",
                run_id=run_id,
                session_id=session_id,
                assigned_agent=EVIDENCE_RETRIEVER,
                objective=evidence_objective,
                task_type=evidence_type,
                expected_output_type="evidence_analysis",
                priority=1,
                metadata=metadata,
            )
        )
        specialist_ids.append("task_evidence")

    if signals.personal_portfolio_requested:
        portfolio_type = "analyze_portfolio_fit" if signals.has_stock_subject else "analyze_portfolio"
        portfolio_objective = (
            "读取当前用户的真实模拟盘账户、持仓、现金和用户画像，分析指定股票与当前组合的适配关系。"
            if signals.has_stock_subject
            else "读取当前用户的真实模拟盘账户、持仓、现金和用户画像，分析当前组合状态。"
        )
        tasks.append(
            _task(
                task_id="task_portfolio",
                run_id=run_id,
                session_id=session_id,
                assigned_agent=PORTFOLIO_ANALYST,
                objective=portfolio_objective,
                task_type=portfolio_type,
                expected_output_type="portfolio_analysis",
                priority=1,
                metadata=metadata,
            )
        )
        specialist_ids.append("task_portfolio")

    if signals.personal_risk_requested:
        # The account/portfolio snapshot is deliberately queried first and passed
        # through the standardized dependency contract.
        tasks.append(
            _task(
                task_id="task_risk",
                run_id=run_id,
                session_id=session_id,
                assigned_agent=RISK_ANALYST,
                objective="基于 Portfolio Agent 已查询的当前账户与组合结果，分析风险、集中度、波动和权限约束。",
                task_type="analyze_risk",
                dependencies=["task_portfolio"],
                expected_output_type="risk_analysis",
                priority=2,
                metadata=metadata,
            )
        )
        specialist_ids.append("task_risk")

    if not specialist_ids:
        return None

    tasks.append(
        _task(
            task_id="task_report",
            run_id=run_id,
            session_id=session_id,
            assigned_agent=REPORT_WRITER,
            objective="仅依据上游 standardized_agent_results 汇总用户需要的最终回答。",
            task_type="write_report",
            dependencies=specialist_ids,
            expected_output_type="report_draft",
            priority=3,
            metadata=metadata,
        )
    )
    return tasks, {
        "planner": "stable_agent_contract",
        "request_mode": "analysis",
        "contract_id": (
            "personal_portfolio_risk"
            if signals.personal_risk_requested
            else "personal_portfolio_fit"
            if signals.personal_portfolio_requested and signals.has_stock_subject
            else "personal_portfolio"
            if signals.personal_portfolio_requested
            else "stock_comparison"
            if signals.comparison_requested
            else "single_stock_analysis"
        ),
        "fallback_used": False,
        "legacy_task_plan_consumed": False,
        "keyword_business_fallback_used": False,
        "tool_visibility": "none",
        "signals": {
            "stock_code_count": len(signals.stock_codes),
            "has_stock_subject": signals.has_stock_subject,
            "comparison_requested": signals.comparison_requested,
            "personal_portfolio_requested": signals.personal_portfolio_requested,
            "personal_risk_requested": signals.personal_risk_requested,
        },
    }


def enforce_risk_dependency(tasks: list[AgentTask]) -> list[AgentTask]:
    """Guarantee that every Risk Agent consumes a Portfolio Agent result first."""

    portfolio_tasks = [task for task in tasks if task.assigned_agent == PORTFOLIO_ANALYST]
    risk_tasks = [task for task in tasks if task.assigned_agent == RISK_ANALYST]
    if risk_tasks and not portfolio_tasks:
        template = risk_tasks[0]
        portfolio = _task(
            task_id="task_portfolio_prerequisite",
            run_id=template.run_id,
            session_id=template.session_id,
            assigned_agent=PORTFOLIO_ANALYST,
            objective="先读取当前用户的真实账户、持仓、现金和用户画像，形成风险分析所需的组合快照。",
            task_type="analyze_portfolio",
            expected_output_type="portfolio_analysis",
            priority=max(0, template.priority - 1),
            metadata={**dict(template.metadata), "inserted_for_risk_dependency": True},
        )
        tasks.insert(0, portfolio)
        portfolio_tasks = [portfolio]

    if portfolio_tasks:
        portfolio_id = portfolio_tasks[0].task_id
        for task in risk_tasks:
            task.dependency_task_ids = list(dict.fromkeys([portfolio_id, *task.dependency_task_ids]))
            task.status = TaskStatus.PENDING

    report_tasks = [task for task in tasks if task.assigned_agent == REPORT_WRITER]
    non_report_ids = [task.task_id for task in tasks if task.assigned_agent != REPORT_WRITER]
    for task in report_tasks:
        task.dependency_task_ids = list(dict.fromkeys([*task.dependency_task_ids, *non_report_ids]))
        task.status = TaskStatus.PENDING if task.dependency_task_ids else TaskStatus.READY
    return tasks




def enforce_analysis_agent_scope(tasks: list[AgentTask], query: str) -> list[AgentTask]:
    """Remove portfolio/risk roles that the user did not explicitly request."""

    signals = analyse_request_signals(query)
    scoped: list[AgentTask] = []
    for task in tasks:
        if task.assigned_agent == PORTFOLIO_ANALYST and not signals.personal_portfolio_requested:
            continue
        if task.assigned_agent == RISK_ANALYST and not signals.personal_risk_requested:
            continue
        scoped.append(task)

    # A report cannot be the only remaining task. Returning an empty plan makes
    # the coordinator reject the invalid LLM plan instead of asking the user for
    # an internal specialist result.
    if not any(task.assigned_agent != REPORT_WRITER for task in scoped):
        return []

    valid_ids = {task.task_id for task in scoped}
    for task in scoped:
        task.dependency_task_ids = [
            dependency
            for dependency in task.dependency_task_ids
            if dependency in valid_ids and dependency != task.task_id
        ]
        task.status = TaskStatus.READY if not task.dependency_task_ids else TaskStatus.PENDING
    return enforce_risk_dependency(scoped)


def normalize_context_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(key or "").strip().lower()).strip("_")


def is_system_queryable_context_key(key: Any) -> bool:
    normalized = normalize_context_key(key)
    if normalized in _SYSTEM_QUERYABLE_CONTEXT_KEYS:
        return True
    return any(fragment in normalized for fragment in _SYSTEM_QUERYABLE_FRAGMENTS)


def _normalise_date(value: Any) -> str:
    text = str(value or "").strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return ""
    return ""


def extract_explicit_as_of_date(
    current_user_request: str,
    execution_context: dict[str, Any] | None,
) -> str:
    """Read an as-of date only from explicit current-turn user input.

    Inherited context, model-generated parameters and memory summaries are ignored.
    """

    context = dict(execution_context or {})
    candidates: list[Any] = []
    direct = context.get("explicit_as_of_date")
    if direct not in (None, ""):
        candidates.append(direct)
    for container_key in ("turn_resolution", "conversation_state"):
        container = context.get(container_key)
        if not isinstance(container, dict):
            continue
        explicit = container.get("explicit_parameters")
        if isinstance(explicit, dict) and explicit.get("as_of_date") not in (None, ""):
            candidates.append(explicit.get("as_of_date"))
    candidates.append(str(current_user_request or ""))
    for candidate in candidates:
        normalized = _normalise_date(candidate)
        if normalized:
            return normalized
    return ""


def runtime_account_id(execution_context: dict[str, Any] | None) -> str:
    context = dict(execution_context or {})
    direct = str(context.get("account_id") or "").strip()
    if direct:
        return direct
    strategy = context.get("strategy_conversation_context")
    if isinstance(strategy, dict):
        value = str(strategy.get("account_id") or "").strip()
        if value:
            return value
    return ""


def sanitize_runtime_parameters(
    parameters: dict[str, Any] | None,
    *,
    user_id: str,
    current_user_request: str,
    execution_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply authoritative runtime identity/date values after any model planning."""

    args = dict(parameters or {})
    args["user_id"] = str(user_id or "default")

    account_id = runtime_account_id(execution_context)
    if account_id:
        args["account_id"] = account_id
    else:
        # Never trust an account identity invented by a model. Portfolio adapters
        # derive the active account from the authoritative user_id when omitted.
        args.pop("account_id", None)

    explicit_date = extract_explicit_as_of_date(current_user_request, execution_context)
    if explicit_date:
        args["as_of_date"] = explicit_date
    else:
        args.pop("as_of_date", None)
    return args


def deterministic_completion_payload(
    *,
    unified_execution: dict[str, Any],
    logic_error: bool = False,
) -> dict[str, Any]:
    """Assess the single-entry Agent result without another LLM observer call."""

    if logic_error:
        return {
            "status": "invalid",
            "produced_outputs": [],
            "missing_outputs": ["standardized_agent_results"],
            "conflict_outputs": [],
            "invalid_reasons": ["deterministic_logic_integrity_failed"],
            "next_action": "block",
            "reason_summary": "Deterministic integrity validation rejected the Agent result.",
            "confidence": 1.0,
            "llm_used": False,
            "assessment_source": "single_entry_deterministic_completion",
        }

    payload = dict(unified_execution or {})
    standardized = payload.get("standardized_agent_results")
    items = standardized.get("items") if isinstance(standardized, dict) else []
    items = [item for item in list(items or []) if isinstance(item, dict)]
    statuses = [str(item.get("status") or "").lower() for item in items]
    produced = ["standardized_agent_results"] if items else []

    missing_context = [item for item in payload.get("missing_context") or [] if isinstance(item, dict)]
    need_clarification = bool(payload.get("need_clarification"))
    execution_status = str(payload.get("execution_status") or "").lower()
    control_action = str(payload.get("control_action") or "").lower()
    has_proposal = any(
        item.get("proposal_id") or item.get("plan_id")
        for item in items
    ) or any(status == "proposal_ready" for status in statuses)
    if has_proposal:
        produced.append("proposal")

    if need_clarification:
        missing_outputs = [str(item.get("key") or "required_context") for item in missing_context]
        return {
            "status": "missing",
            "produced_outputs": produced,
            "missing_outputs": list(dict.fromkeys(missing_outputs)) or ["required_context"],
            "conflict_outputs": [],
            "invalid_reasons": [],
            "next_action": "ask_user",
            "reason_summary": "A specialist exhausted system-accessible sources and still requires user-provided target information.",
            "confidence": 1.0,
            "llm_used": False,
            "assessment_source": "single_entry_deterministic_completion",
        }

    if missing_context:
        categories = {str(item.get("category") or "unknown") for item in missing_context}
        retryable = any(bool(item.get("retryable")) for item in missing_context)
        next_action = "retry" if retryable and categories <= {"tool_failure", "upstream_result"} else "report_limitation"
        return {
            "status": "partial" if produced else "missing",
            "produced_outputs": produced,
            "missing_outputs": list(
                dict.fromkeys(str(item.get("key") or "required_context") for item in missing_context)
            ),
            "conflict_outputs": [],
            "invalid_reasons": [],
            "next_action": next_action,
            "reason_summary": (
                "System data or an internal dependency is unavailable; user input is not required."
            ),
            "confidence": 1.0,
            "llm_used": False,
            "assessment_source": "single_entry_deterministic_completion",
        }

    failed = sum(status in {"failed", "blocked"} for status in statuses)
    completed = sum(status in {"completed", "partial", "proposal_ready"} for status in statuses)
    if has_proposal and control_action not in {"confirm", "reject"}:
        status = "complete" if completed else "partial"
        next_action = "wait_approval"
    elif execution_status == "completed" and bool(payload.get("success")) and failed == 0:
        status = "complete"
        next_action = "finish"
    elif completed:
        status = "partial"
        next_action = "report_limitation"
    else:
        status = "missing"
        next_action = "report_limitation"

    missing_outputs = [] if status == "complete" else ([] if produced else ["standardized_agent_results"])
    return {
        "status": status,
        "produced_outputs": list(dict.fromkeys(produced)),
        "missing_outputs": missing_outputs,
        "conflict_outputs": [],
        "invalid_reasons": [] if completed else ["no_successful_standardized_agent_result"],
        "next_action": next_action,
        "reason_summary": (
            "The single-entry Agent result satisfies the deterministic standardized-result contract."
            if status == "complete"
            else "The single-entry Agent result is usable but incomplete; no legacy Completion Observer was called."
        ),
        "confidence": 1.0,
        "llm_used": False,
        "assessment_source": "single_entry_deterministic_completion",
    }

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPERVISOR = "supervisor"
MARKET_INTELLIGENCE = "market_intelligence"
PORTFOLIO_ANALYSIS = "portfolio_analysis"
REPORTING = "reporting"
RISK_OPERATION = "risk_operation"


@dataclass(frozen=True)
class AgentSpec:
    role: str
    role_prompt: str
    tool_whitelist: frozenset[str] = field(default_factory=frozenset)
    context_selector: tuple[str, ...] = ()


_SPECS: dict[str, AgentSpec] = {
    SUPERVISOR: AgentSpec(
        role=SUPERVISOR,
        role_prompt=(
            "Coordinate read-only financial analysis tasks, choose specialist "
            "agents, preserve business safety boundaries, and never execute "
            "protected writes."
        ),
        tool_whitelist=frozenset(),
        context_selector=("query", "decomposition", "business_constraints"),
    ),
    MARKET_INTELLIGENCE: AgentSpec(
        role=MARKET_INTELLIGENCE,
        role_prompt=(
            "Retrieve market ranking, stock news, RAG evidence, and stock-level "
            "analysis. Do not modify portfolio data."
        ),
        tool_whitelist=frozenset(
            {
                "ranking",
                "stock_news",
                "stock_rag",
                "stock_analysis",
            }
        ),
        context_selector=("query", "ranking", "news", "rag", "stock_analysis"),
    ),
    PORTFOLIO_ANALYSIS: AgentSpec(
        role=PORTFOLIO_ANALYSIS,
        role_prompt=(
            "Read paper portfolio state, portfolio risk, and read-only position "
            "recommendations. Produce analysis only; do not commit actions."
        ),
        tool_whitelist=frozenset(
            {
                "portfolio_state",
                "portfolio_risk",
                "position_recommendation",
                "portfolio.recommend_position",
            }
        ),
        context_selector=("query", "portfolio", "risk", "market_handoff"),
    ),
    REPORTING: AgentSpec(
        role=REPORTING,
        role_prompt=(
            "Summarize structured outputs from other agents into a traceable "
            "final response. Do not call write tools."
        ),
        tool_whitelist=frozenset(),
        context_selector=("market_output", "portfolio_output", "sources"),
    ),
    RISK_OPERATION: AgentSpec(
        role=RISK_OPERATION,
        role_prompt=(
            "Validate paper-position operation constraints and create a "
            "confirmation-required proposal. Never execute or commit orders."
        ),
        tool_whitelist=frozenset(
            {
                "manual_position_operation_tool",
                "portfolio.preview_manual_change",
            }
        ),
        context_selector=("query", "portfolio_output", "market_output", "operation_request"),
    ),
}


INTENT_ROLE_MAP: dict[str, str] = {
    "ranking": MARKET_INTELLIGENCE,
    "stock_news": MARKET_INTELLIGENCE,
    "stock_rag": MARKET_INTELLIGENCE,
    "stock_analysis": MARKET_INTELLIGENCE,
    "portfolio_state": PORTFOLIO_ANALYSIS,
    "portfolio_risk": PORTFOLIO_ANALYSIS,
    "position_recommendation": PORTFOLIO_ANALYSIS,
}


READ_ONLY_MULTI_AGENT_INTENTS = frozenset(INTENT_ROLE_MAP)
IGNORABLE_READ_ONLY_INTENTS = frozenset({"user_profile"})


def get_agent_spec(role: str) -> AgentSpec:
    try:
        return _SPECS[str(role)]
    except KeyError as exc:
        raise ValueError(f"unknown_agent_role:{role}") from exc


def list_agent_specs() -> list[dict[str, Any]]:
    return [
        {
            "role": spec.role,
            "role_prompt": spec.role_prompt,
            "tool_whitelist": sorted(spec.tool_whitelist),
            "context_selector": list(spec.context_selector),
        }
        for spec in _SPECS.values()
    ]


def role_for_intent(intent: str) -> str | None:
    name = str(intent or "")
    if name.startswith("mcp."):
        return MARKET_INTELLIGENCE
    return INTENT_ROLE_MAP.get(name)


def validate_tool_allowed(role: str, tool_name: str) -> None:
    spec = get_agent_spec(role)
    name = str(tool_name or "")
    if name.startswith("mcp."):
        try:
            from agent.mcp.registry_bridge import validate_mcp_tool_allowed_for_role

            validate_mcp_tool_allowed_for_role(role, name)
            return
        except Exception as exc:
            raise PermissionError(f"tool_not_allowed_for_agent:{role}:{name}") from exc
    if name not in spec.tool_whitelist:
        raise PermissionError(f"tool_not_allowed_for_agent:{role}:{name}")


def tasks_for_role(tasks: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for task in tasks:
        if role_for_intent(str(task.get("intent") or "")) == role:
            selected.append(dict(task))
    return selected


def is_read_only_multi_agent_candidate(decomposition: dict[str, Any]) -> bool:
    tasks = decomposition.get("tasks") if isinstance(decomposition, dict) else []
    if not isinstance(tasks, list) or len(tasks) < 2:
        return False
    intents = {str(task.get("intent") or "") for task in tasks if isinstance(task, dict)}
    mcp_intents = {intent for intent in intents if intent.startswith("mcp.")}
    specialist_intents = (intents & READ_ONLY_MULTI_AGENT_INTENTS) | mcp_intents
    unsupported = intents - READ_ONLY_MULTI_AGENT_INTENTS - IGNORABLE_READ_ONLY_INTENTS - mcp_intents
    return len(specialist_intents) >= 2 and not unsupported

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .handoff_types import AgentRole, HandoffRequest


WRITE_TOOL_NAMES = frozenset(
    {
        "approval.confirm_plan",
        "paper_trade_execute",
        "paper_trading_execution_tool",
        "strategy_confirmation_execute",
        "strategy_disable_execute",
        "capital_management_execute",
        "backfill_execute",
        "portfolio.commit_paper_trade",
        "portfolio.commit_adjust_position",
    }
)

PROPOSAL_TOOL_NAMES = frozenset(
    {
        "manual_position_operation_tool",
        "portfolio.preview_manual_change",
        "portfolio.preview_paper_trade",
        "portfolio.preview_adjust_position",
        "rebalance_plan",
        "adjust_position",
        "strategy_builder_tool",
        "strategy_management_tool",
        "strategy.disable_preview",
        "capital_management_preview",
        "backfill_preview",
    }
)

READ_TOOL_NAMES_BY_ROLE: dict[AgentRole, frozenset[str]] = {
    AgentRole.PORTFOLIO_ANALYST: frozenset(
        {
            "portfolio_state",
            "portfolio_risk",
            "position_recommendation",
            "portfolio.recommend_position",
            "user_profile",
        }
    ),
    AgentRole.RISK_ANALYST: frozenset(
        {
            "portfolio_state",
            "portfolio_risk",
            "position_recommendation",
            "portfolio.recommend_position",
            "risk_summary",
        }
    ),
    AgentRole.EVIDENCE_RETRIEVER: frozenset(
        {
            "ranking",
            "classic_ranking",
            "stock_lookup",
            "classic_stock_score",
            "stock_analysis",
            "stock_news",
            "stock_rag",
        }
    ),
    AgentRole.STRATEGY_GUARD: PROPOSAL_TOOL_NAMES
    | frozenset(
        {
            "portfolio_state",
            "portfolio_risk",
            "position_recommendation",
            "portfolio.recommend_position",
        }
    ),
    AgentRole.REPORT_WRITER: frozenset(),
    AgentRole.SYSTEM_DIAGNOSTIC: frozenset(
        {
            "system_status",
            "scheduler_status",
            "runtime_status",
            "message_trace",
            "memory_status",
            "react_status",
            "reflection_status",
        }
    ),
    AgentRole.COORDINATOR: frozenset(
        {
            "portfolio_state",
            "portfolio_risk",
            "ranking",
            "stock_analysis",
            "stock_news",
            "stock_rag",
            "system_status",
            *PROPOSAL_TOOL_NAMES,
            *WRITE_TOOL_NAMES,
        }
    ),
}

SENSITIVE_KEYS = frozenset(
    {
        "confirmation_token",
        "confirmation_token_hash",
        "api_key",
        "authorization",
        "authorization_header",
        "cookie",
        "db_path",
        "database_path",
        "internal_file_path",
        "local_path",
        "output_dir",
        "password",
        "path",
        "raw_evidence",
        "raw_payload",
        "raw_positions",
        "raw_tool_payload",
        "secret",
        "stack",
        "stack_trace",
        "traceback",
        "tushare_token",
    }
)


@dataclass(frozen=True)
class HandoffPolicy:
    default_max_depth: int = 4
    allowed_edges: dict[AgentRole, frozenset[AgentRole]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.allowed_edges:
            return
        object.__setattr__(
            self,
            "allowed_edges",
            {
                AgentRole.COORDINATOR: frozenset(role for role in AgentRole if role != AgentRole.COORDINATOR),
                AgentRole.EVIDENCE_RETRIEVER: frozenset({AgentRole.PORTFOLIO_ANALYST, AgentRole.REPORT_WRITER}),
                AgentRole.PORTFOLIO_ANALYST: frozenset({AgentRole.RISK_ANALYST, AgentRole.STRATEGY_GUARD, AgentRole.REPORT_WRITER}),
                AgentRole.RISK_ANALYST: frozenset({AgentRole.STRATEGY_GUARD, AgentRole.REPORT_WRITER}),
                AgentRole.STRATEGY_GUARD: frozenset({AgentRole.COORDINATOR, AgentRole.REPORT_WRITER}),
                AgentRole.REPORT_WRITER: frozenset({AgentRole.COORDINATOR}),
                AgentRole.SYSTEM_DIAGNOSTIC: frozenset({AgentRole.REPORT_WRITER, AgentRole.COORDINATOR}),
            },
        )

    @classmethod
    def default(cls) -> "HandoffPolicy":
        return cls()

    def can_handoff(
        self,
        source_role: AgentRole | str,
        target_role: AgentRole | str,
        *,
        depth: int = 0,
        tool_name: str = "",
    ) -> bool:
        source = AgentRole.from_value(source_role)
        target = AgentRole.from_value(target_role)
        if depth >= self.max_handoff_depth():
            return False
        if target not in self.allowed_edges.get(source, frozenset()):
            return False
        if tool_name and tool_name not in self.allowed_tools_for_role(target):
            if not (target == AgentRole.EVIDENCE_RETRIEVER and str(tool_name).startswith("mcp.")):
                return False
        return True

    def allowed_tools_for_role(self, role: AgentRole | str) -> list[str]:
        agent_role = AgentRole.from_value(role)
        return sorted(READ_TOOL_NAMES_BY_ROLE.get(agent_role, frozenset()))

    def blocked_tools_for_role(self, role: AgentRole | str) -> list[str]:
        agent_role = AgentRole.from_value(role)
        blocked = set(WRITE_TOOL_NAMES)
        if agent_role not in {AgentRole.COORDINATOR, AgentRole.STRATEGY_GUARD}:
            blocked |= set(PROPOSAL_TOOL_NAMES)
        if agent_role == AgentRole.STRATEGY_GUARD:
            blocked |= set(WRITE_TOOL_NAMES)
        if agent_role == AgentRole.COORDINATOR:
            blocked = set()
        return sorted(blocked)

    def requires_approval(self, role: AgentRole | str, *, tool_name: str = "", operation_type: str = "") -> bool:
        del role
        name = str(tool_name or "")
        operation = str(operation_type or "").lower()
        return name in WRITE_TOOL_NAMES or name in PROPOSAL_TOOL_NAMES or operation in {"write", "proposal"}

    def can_write_business_state(self, role: AgentRole | str) -> bool:
        return AgentRole.from_value(role) == AgentRole.COORDINATOR

    def can_show_to_llm(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return not self._is_sensitive(key, value=value, path=path)

    def can_show_to_ui(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return not self._is_sensitive(key, value=value, path=path)

    def max_handoff_depth(self) -> int:
        return max(1, int(self.default_max_depth))

    def validate_request(self, request: HandoffRequest | dict[str, Any]) -> list[str]:
        req = request if isinstance(request, HandoffRequest) else HandoffRequest.from_dict(dict(request or {}))
        errors: list[str] = []
        if not self.can_handoff(req.source_role, req.target_role):
            errors.append(f"handoff_not_allowed:{req.source_role.value}->{req.target_role.value}")
        allowed = set(self.allowed_tools_for_role(req.target_role))
        for tool_name in req.allowed_tools:
            if tool_name.startswith("mcp.") and req.target_role == AgentRole.EVIDENCE_RETRIEVER:
                continue
            if tool_name not in allowed:
                errors.append(f"tool_not_allowed_for_role:{req.target_role.value}:{tool_name}")
        if req.target_role != AgentRole.COORDINATOR:
            writes = [tool for tool in req.allowed_tools if tool in WRITE_TOOL_NAMES]
            if writes:
                errors.append("specialist_write_tool_blocked:" + ",".join(sorted(writes)))
        if self.contains_sensitive_data(req.to_dict()):
            errors.append("sensitive_data_detected")
        return errors

    def contains_sensitive_data(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if self._is_sensitive(str(key), value=item):
                    return True
                if self.contains_sensitive_data(item):
                    return True
        if isinstance(value, list):
            return any(self.contains_sensitive_data(item) for item in value)
        return False

    def _is_sensitive(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered in SENSITIVE_KEYS:
            return True
        if any(marker in lowered for marker in ("api_key", "password", "secret", "token")):
            return True
        if any(marker in joined for marker in ("raw_payload", "raw_positions", "raw_evidence", "stack_trace")):
            return True
        if isinstance(value, str):
            text = value.lower()
            if "confirmation_token" in text or "traceback" in text:
                return True
            if len(value) >= 3 and (":\\" in value or value.startswith("/") or "appdata\\local" in text):
                return True
        return False

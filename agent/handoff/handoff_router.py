from __future__ import annotations

from typing import Any

from agent.reflection.critic_types import CriticAction

from .handoff_policy import HandoffPolicy, PROPOSAL_TOOL_NAMES
from .handoff_types import AgentRole, HandoffPriority, HandoffRequest


class HandoffRouter:
    def __init__(self, policy: HandoffPolicy | None = None) -> None:
        self.policy = policy or HandoffPolicy.default()

    def route_by_user_goal(self, user_goal: Any) -> list[AgentRole]:
        text = _flatten_text(user_goal)
        roles: list[AgentRole] = []
        if _contains_any(text, ("news", "rag", "evidence", "ranking", "rank", "market", "stock", "新闻", "证据", "排名", "行情", "个股")):
            roles.append(AgentRole.EVIDENCE_RETRIEVER)
        if _contains_any(text, ("portfolio", "position", "holding", "account", "持仓", "账户", "模拟盘", "组合")):
            roles.append(AgentRole.PORTFOLIO_ANALYST)
        if _contains_any(text, ("risk", "drawdown", "exposure", "风险", "回撤", "集中度")):
            roles.append(AgentRole.RISK_ANALYST)
        if _contains_any(text, ("adjust", "rebalance", "proposal", "buy", "sell", "调仓", "减仓", "加仓", "买", "卖", "建议")):
            for role in (AgentRole.PORTFOLIO_ANALYST, AgentRole.RISK_ANALYST, AgentRole.STRATEGY_GUARD):
                if role not in roles:
                    roles.append(role)
        if _contains_any(text, ("system", "scheduler", "status", "health", "系统", "调度", "状态", "监控")):
            roles.append(AgentRole.SYSTEM_DIAGNOSTIC)
        if not roles:
            roles.append(AgentRole.REPORT_WRITER)
        if AgentRole.REPORT_WRITER not in roles:
            roles.append(AgentRole.REPORT_WRITER)
        return _dedupe_roles(roles)

    def route_by_critic_action(
        self,
        critic_action: CriticAction | str,
        *,
        handoff_hint: str = "",
        issues: list[dict[str, Any]] | None = None,
    ) -> list[AgentRole]:
        action = CriticAction.from_value(critic_action)
        hint = " ".join([handoff_hint, _flatten_text(issues or [])]).lower()
        if action == CriticAction.BLOCK_AND_REPORT:
            return [AgentRole.COORDINATOR]
        if action == CriticAction.REQUIRE_APPROVAL:
            return [AgentRole.COORDINATOR]
        if action == CriticAction.REPLAN_READONLY:
            return [AgentRole.COORDINATOR]
        if action != CriticAction.HANDOFF_REQUESTED:
            return []
        if _contains_any(hint, ("evidence", "news", "rag", "market", "ranking", "证据", "新闻", "检索", "排名")):
            return [AgentRole.EVIDENCE_RETRIEVER]
        if _contains_any(hint, ("risk", "constraint", "guard", "风险", "约束")):
            return [AgentRole.RISK_ANALYST]
        if _contains_any(hint, ("portfolio", "position", "holding", "持仓", "组合")):
            return [AgentRole.PORTFOLIO_ANALYST]
        if _contains_any(hint, ("proposal", "approval", "rebalance", "调仓", "审批", "确认")):
            return [AgentRole.STRATEGY_GUARD]
        if _contains_any(hint, ("system", "runtime", "tool", "系统", "运行")):
            return [AgentRole.SYSTEM_DIAGNOSTIC]
        return [AgentRole.COORDINATOR]

    def route_by_missing_context(self, missing_context: Any) -> list[AgentRole]:
        text = _flatten_text(missing_context)
        if _contains_any(text, ("evidence", "news", "rag", "source", "证据", "新闻", "来源")):
            return [AgentRole.EVIDENCE_RETRIEVER]
        if _contains_any(text, ("portfolio", "position", "account", "持仓", "账户")):
            return [AgentRole.PORTFOLIO_ANALYST]
        if _contains_any(text, ("risk", "constraint", "exposure", "风险", "约束")):
            return [AgentRole.RISK_ANALYST]
        if _contains_any(text, ("system", "runtime", "status", "系统", "运行")):
            return [AgentRole.SYSTEM_DIAGNOSTIC]
        return [AgentRole.COORDINATOR]

    def route_by_tool_need(self, tool_name: str) -> AgentRole:
        name = str(tool_name or "")
        if name.startswith("mcp."):
            return AgentRole.EVIDENCE_RETRIEVER
        if name in PROPOSAL_TOOL_NAMES:
            return AgentRole.STRATEGY_GUARD
        for role in AgentRole:
            if name in self.policy.allowed_tools_for_role(role) and role != AgentRole.COORDINATOR:
                return role
        return AgentRole.COORDINATOR

    def route_by_risk_level(self, risk_level: str) -> list[AgentRole]:
        text = str(risk_level or "").strip().lower()
        if text in {"critical", "blocking", "high", "高风险", "极高"}:
            return [AgentRole.RISK_ANALYST, AgentRole.STRATEGY_GUARD]
        if text in {"medium", "moderate", "中风险"}:
            return [AgentRole.RISK_ANALYST, AgentRole.REPORT_WRITER]
        return [AgentRole.PORTFOLIO_ANALYST, AgentRole.REPORT_WRITER]

    def build_request(
        self,
        *,
        source_role: AgentRole | str = AgentRole.COORDINATOR,
        target_role: AgentRole | str,
        reason: str,
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        input_summary: dict[str, Any] | None = None,
        context_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
        observation_refs: list[dict[str, Any]] | None = None,
        replan_refs: list[dict[str, Any]] | None = None,
        critic_refs: list[dict[str, Any]] | None = None,
        memory_refs: list[dict[str, Any]] | None = None,
        artifact_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
        priority: HandoffPriority | str = HandoffPriority.NORMAL,
        tool_names: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HandoffRequest:
        target = AgentRole.from_value(target_role)
        allowed = self.policy.allowed_tools_for_role(target)
        requested = [str(item) for item in (tool_names or []) if str(item or "").strip()]
        if requested:
            allowed = [tool for tool in requested if tool in allowed or (target == AgentRole.EVIDENCE_RETRIEVER and tool.startswith("mcp."))]
        return HandoffRequest(
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            source_role=AgentRole.from_value(source_role),
            target_role=target,
            reason=reason,
            priority=HandoffPriority.from_value(priority),
            input_summary=dict(input_summary or {}),
            context_refs=list(context_refs or []),
            message_refs=list(message_refs or []),
            observation_refs=list(observation_refs or []),
            replan_refs=list(replan_refs or []),
            critic_refs=list(critic_refs or []),
            memory_refs=list(memory_refs or []),
            artifact_refs=list(artifact_refs or []),
            approval_refs=list(approval_refs or []),
            allowed_tools=allowed,
            blocked_tools=self.policy.blocked_tools_for_role(target),
            requires_approval=any(self.policy.requires_approval(target, tool_name=tool) for tool in allowed),
            metadata=dict(metadata or {}),
        )


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join([str(key) + " " + _flatten_text(item) for key, item in value.items()]).lower()
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value).lower()
    return str(value or "").lower()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in text for marker in markers)


def _dedupe_roles(roles: list[AgentRole]) -> list[AgentRole]:
    seen: set[AgentRole] = set()
    result: list[AgentRole] = []
    for role in roles:
        if role not in seen:
            seen.add(role)
            result.append(role)
    return result

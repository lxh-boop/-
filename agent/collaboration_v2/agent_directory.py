from __future__ import annotations

from typing import Any

from .models import AgentCapabilityCard


COORDINATOR = "COORDINATOR"
EVIDENCE_RETRIEVER = "EVIDENCE_RETRIEVER"
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
RISK_ANALYST = "RISK_ANALYST"
STRATEGY_GUARD = "STRATEGY_GUARD"
REPORT_WRITER = "REPORT_WRITER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"


class AgentDirectory:
    """Coordinator-facing directory.

    Cards describe business capabilities only. They deliberately omit tool names,
    schemas, API endpoints, database tables and implementation paths.
    """

    def __init__(self) -> None:
        cards = [
            AgentCapabilityCard(
                agent_id=EVIDENCE_RETRIEVER,
                role=EVIDENCE_RETRIEVER,
                description="检索并整理股票、市场、新闻、公告、RAG 与模型证据。",
                accepted_task_types=[
                    "retrieve_evidence",
                    "analyze_stock_evidence",
                    "compare_stock_evidence",
                    "resolve_context",
                ],
                input_description="证据目标、对象范围、时间范围以及会话上下文引用。",
                output_types=["evidence_analysis", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=PORTFOLIO_ANALYST,
                role=PORTFOLIO_ANALYST,
                description="分析模拟盘账户、持仓、现金、组合结构和目标组合适配性。",
                accepted_task_types=[
                    "analyze_portfolio",
                    "analyze_portfolio_fit",
                    "compare_portfolios",
                    "resolve_context",
                ],
                input_description="组合分析目标、候选对象以及会话上下文引用。",
                output_types=["portfolio_analysis", "portfolio_comparison", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=RISK_ANALYST,
                role=RISK_ANALYST,
                description="分析风险画像、集中度、波动、权限约束和方案前后风险变化。",
                accepted_task_types=[
                    "analyze_risk",
                    "compare_risk",
                    "review_risk_constraints",
                    "resolve_context",
                ],
                input_description="风险问题、组合或候选方案，以及会话上下文引用。",
                output_types=["risk_analysis", "risk_comparison", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=STRATEGY_GUARD,
                role=STRATEGY_GUARD,
                description="生成或审查模拟盘调整预案，确保建议与审批、重新校验和提交边界一致。",
                accepted_task_types=[
                    "review_strategy",
                    "build_proposal",
                    "review_proposal",
                ],
                input_description="策略目标、组合与风险结果引用；只能生成或审查预案。",
                output_types=["strategy_review", "proposal"],
                supports_parallel=False,
                can_generate_proposal=True,
            ),
            AgentCapabilityCard(
                agent_id=REPORT_WRITER,
                role=REPORT_WRITER,
                description="将多个专业 Agent 的标准结果整理成结构化报告草稿。",
                accepted_task_types=["write_report", "summarize_results"],
                input_description="上游专业 Agent 的标准结果引用。",
                output_types=["report_draft"],
                supports_parallel=False,
            ),
            AgentCapabilityCard(
                agent_id=SYSTEM_DIAGNOSTIC,
                role=SYSTEM_DIAGNOSTIC,
                description="诊断 Agent、RAG、模型、调度、数据库与运行链路状态。",
                accepted_task_types=["diagnose_system", "inspect_runtime", "resolve_context"],
                input_description="故障现象、运行引用和会话上下文引用。",
                output_types=["diagnostic_analysis", "context_resolution"],
                supports_parallel=True,
            ),
        ]
        self._cards = {card.agent_id: card for card in cards}

    def get(self, agent_id: str) -> AgentCapabilityCard:
        key = str(agent_id or "").upper()
        if key not in self._cards:
            raise KeyError(f"unknown specialist agent: {key}")
        return self._cards[key]

    def list_cards(self) -> list[AgentCapabilityCard]:
        return list(self._cards.values())

    def safe_catalog(self) -> list[dict[str, Any]]:
        return [card.safe_for_coordinator() for card in self.list_cards()]

    def supports(self, agent_id: str, task_type: str) -> bool:
        try:
            card = self.get(agent_id)
        except KeyError:
            return False
        return str(task_type or "") in card.accepted_task_types

    def candidates_for(self, task_type: str) -> list[str]:
        task = str(task_type or "")
        return [card.agent_id for card in self.list_cards() if task in card.accepted_task_types]

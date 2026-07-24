from __future__ import annotations

from typing import Any

from .models import AgentCapabilityCard


COORDINATOR = "COORDINATOR"
EVIDENCE_RETRIEVER = "EVIDENCE_RETRIEVER"
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
GRAPH_IMPACT_ANALYST = "GRAPH_IMPACT_ANALYST"
RISK_ANALYST = "RISK_ANALYST"
STRATEGY_GUARD = "STRATEGY_GUARD"
REPORT_WRITER = "REPORT_WRITER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"


class AgentDirectory:
    """Coordinator-facing Worker capability cards only.

    The Main Agent never receives private tools, provider identifiers, Cypher,
    database schemas or internal prompts.
    """

    def __init__(self) -> None:
        cards = [
            AgentCapabilityCard(
                agent_id=EVIDENCE_RETRIEVER,
                role=EVIDENCE_RETRIEVER,
                description="读取新闻、公告、研报、RAG 与市场证据，并把结构化证据写入金融事实图。",
                accepted_task_types=[
                    "retrieve_evidence",
                    "analyze_entity_evidence",
                    "compare_entity_evidence",
                    "ingest_evidence",
                    "resolve_context",
                ],
                input_description="GraphRef 目标、查询目标、时间边界和任务图视图引用。",
                output_types=["evidence_result", "graph_patch", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=PORTFOLIO_ANALYST,
                role=PORTFOLIO_ANALYST,
                description="读取模拟盘账户与持仓，生成权威 PortfolioSnapshot GraphRef，并分析组合结构。",
                accepted_task_types=[
                    "load_portfolio_snapshot",
                    "analyze_portfolio",
                    "analyze_portfolio_fit",
                    "compare_portfolios",
                    "resolve_context",
                ],
                input_description="运行时 user_id、GraphRef 上下文、时间边界和依赖结果引用。",
                output_types=["portfolio_snapshot", "portfolio_analysis", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=GRAPH_IMPACT_ANALYST,
                role=GRAPH_IMPACT_ANALYST,
                description="基于 Neo4j 金融事实图查找新闻、事件或声明到用户持仓的可追踪影响路径。",
                accepted_task_types=[
                    "analyze_graph_impact",
                    "map_evidence_to_holdings",
                    "trace_financial_relation",
                    "resolve_context",
                ],
                input_description="原因 GraphRef、PortfolioSnapshot GraphRef、时间边界和依赖结果引用。",
                output_types=["impact_paths", "impacted_holdings", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=RISK_ANALYST,
                role=RISK_ANALYST,
                description="分析用户风险画像、组合集中度、权限约束和方案前后风险。",
                accepted_task_types=[
                    "analyze_risk",
                    "compare_risk",
                    "review_risk_constraints",
                    "resolve_context",
                ],
                input_description="PortfolioSnapshot GraphRef、候选方案引用和任务图视图。",
                output_types=["risk_analysis", "risk_comparison", "context_resolution"],
                supports_parallel=True,
            ),
            AgentCapabilityCard(
                agent_id=STRATEGY_GUARD,
                role=STRATEGY_GUARD,
                description="生成或审查模拟盘调整 Proposal，并保持 Approval→Revalidate→Commit 边界。",
                accepted_task_types=["review_strategy", "build_proposal", "review_proposal"],
                input_description="GraphRef 目标、组合与风险结果引用；只能生成或审查 Proposal。",
                output_types=["strategy_review", "proposal"],
                supports_parallel=False,
                can_generate_proposal=True,
            ),
            AgentCapabilityCard(
                agent_id=REPORT_WRITER,
                role=REPORT_WRITER,
                description="只依据 GraphWorkerResult 汇总最终报告，不重新解析原始证券代码或新闻正文。",
                accepted_task_types=["write_report", "summarize_results"],
                input_description="上游 GraphWorkerResult 引用。",
                output_types=["report_draft"],
                supports_parallel=False,
            ),
            AgentCapabilityCard(
                agent_id=SYSTEM_DIAGNOSTIC,
                role=SYSTEM_DIAGNOSTIC,
                description="诊断 Agent、Neo4j、RAG、模型、数据库和运行链路状态。",
                accepted_task_types=["diagnose_system", "inspect_runtime", "resolve_context"],
                input_description="故障现象、运行引用和图运行时状态。",
                output_types=["diagnostic_analysis", "context_resolution"],
                supports_parallel=True,
            ),
        ]
        self._cards = {card.agent_id: card for card in cards}

    def get(self, agent_id: str) -> AgentCapabilityCard:
        key = str(agent_id or "").upper()
        if key not in self._cards:
            raise KeyError(f"unknown_worker_agent:{key}")
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

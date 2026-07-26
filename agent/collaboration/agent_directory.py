"""Public Worker capability catalog and private runtime bindings.

The catalog is intentionally honest about the current Worker implementations.
Capabilities that need future Worker/tool work are not advertised to the Main
Agent until their execution path exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .capability_contracts import AgentCapabilityCard, WorkerCapability


COORDINATOR = "COORDINATOR"
EVIDENCE_RESEARCHER = "EVIDENCE_RESEARCHER"
MARKET_ANALYST = "MARKET_ANALYST"
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
GRAPH_IMPACT_ANALYST = "GRAPH_IMPACT_ANALYST"
PORTFOLIO_RISK_ANALYST = "PORTFOLIO_RISK_ANALYST"
STRATEGY_PROPOSAL_BUILDER = "STRATEGY_PROPOSAL_BUILDER"
REPORT_COMPOSER = "REPORT_COMPOSER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"


@dataclass(frozen=True)
class ResolvedWorkerCapability:
    """Private runtime binding resolved after capability-plan validation."""

    capability_id: str
    worker_id: str
    task_type: str
    required_dependency_output_types: tuple[str, ...]
    accepted_dependency_output_types: tuple[str, ...]
    produced_output_types: tuple[str, ...]
    supports_parallel: bool
    can_finalize: bool
    side_effect_scope: str


def _capability(
    capability_id: str,
    task_type: str,
    description: str,
    when_to_use: str,
    *,
    not_for: str = "",
    request_modes: Iterable[str] = ("analysis", "proposal"),
    required_dependencies: Iterable[str] = (),
    accepted_dependencies: Iterable[str] = (),
    outputs: Iterable[str] = (),
    supports_parallel: bool = True,
    can_finalize: bool = False,
    side_effect_scope: str = "read_only",
) -> WorkerCapability:
    produced_outputs = [
        output_type
        for output_type in (*outputs, "worker_result")
        if output_type
    ]
    return WorkerCapability(
        capability_id=capability_id,
        task_type=task_type,
        description=description,
        when_to_use=when_to_use,
        not_for=not_for,
        request_modes=list(request_modes),
        required_dependency_output_types=list(required_dependencies),
        accepted_dependency_output_types=list(accepted_dependencies),
        produced_output_types=list(dict.fromkeys(produced_outputs)),
        supports_parallel=supports_parallel,
        can_finalize=can_finalize,
        side_effect_scope=side_effect_scope,
    )


def _default_cards() -> list[AgentCapabilityCard]:
    """Return capability cards backed by an existing Worker execution path."""

    return [
        AgentCapabilityCard(
            agent_id=EVIDENCE_RESEARCHER,
            role=EVIDENCE_RESEARCHER,
            description="围绕已识别金融对象研究、分析并登记证据。",
            capabilities=[
                _capability(
                    "evidence.research",
                    "research_evidence",
                    "研究已识别金融对象的新闻、公告、研报和知识库证据，可按任务需要分析现有证据、检索新证据或登记衍生图谱引用。",
                    "需要为一个或多个已识别金融对象建立可追踪证据包时使用。",
                    not_for="不负责账户、持仓、组合风险或最终报告。",
                    outputs=("evidence_result", "graph_patch"),
                    side_effect_scope="derived_graph",
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=MARKET_ANALYST,
            role=MARKET_ANALYST,
            description="读取本地市场排名、证券标识和信号摘要并形成分析观察。",
            capabilities=[
                _capability(
                    "market.stock_analysis",
                    "analyze_market_stock",
                    "分析或比较明确证券对象的本地排名、标识和模型信号；多个对象属于同一市场分析能力，不拆成重复 Worker。",
                    "用户需要单只或多只证券的只读市场分析、排名定位或模型信号比较时使用。",
                    not_for="不检索新闻或 RAG 证据，不读取个人账户，不构造或执行交易。",
                    accepted_dependencies=("evidence_result",),
                    outputs=("market_analysis",),
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=PORTFOLIO_ANALYST,
            role=PORTFOLIO_ANALYST,
            description="读取并分析用户当前模拟盘组合。",
            capabilities=[
                _capability(
                    "portfolio.analysis",
                    "analyze_portfolio",
                    "读取当前账户、现金和持仓，形成权威图谱快照并返回持仓结构摘要。",
                    "用户请求涉及自己的账户、持仓、现金、仓位或当前组合结构时使用。",
                    not_for="不用于一般市场分析。",
                    outputs=("portfolio_snapshot", "portfolio_analysis"),
                    side_effect_scope="derived_graph",
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=GRAPH_IMPACT_ANALYST,
            role=GRAPH_IMPACT_ANALYST,
            description="分析金融证据到用户持仓之间的可追踪关系。",
            capabilities=[
                _capability(
                    "graph.impact_analysis",
                    "analyze_graph_impact",
                    "把已验证证据映射到可能受影响的当前持仓。",
                    "已有证据结果和组合快照，需要分析持仓影响时使用。",
                    not_for="不自行检索证据，也不自行读取账户。",
                    required_dependencies=("evidence_result", "portfolio_snapshot"),
                    accepted_dependencies=("evidence_result", "portfolio_snapshot"),
                    outputs=("impact_paths", "impacted_holdings"),
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=PORTFOLIO_RISK_ANALYST,
            role=PORTFOLIO_RISK_ANALYST,
            description="分析用户当前组合风险。",
            capabilities=[
                _capability(
                    "portfolio.risk_analysis",
                    "analyze_portfolio_risk",
                    "分析当前组合的风险、集中度和风险等级。",
                    "已有组合快照且用户要求分析个人组合风险时使用。",
                    not_for="当前不提供候选方案前后风险比较。",
                    required_dependencies=("portfolio_snapshot",),
                    accepted_dependencies=("portfolio_snapshot",),
                    outputs=("risk_analysis",),
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=STRATEGY_PROPOSAL_BUILDER,
            role=STRATEGY_PROPOSAL_BUILDER,
            description="生成等待独立审批的策略 Proposal。",
            capabilities=[
                _capability(
                    "strategy.proposal",
                    "build_strategy_proposal",
                    "根据上游专业结果生成等待审批的策略 Proposal。",
                    "proposal 模式需要形成可审查但未执行的方案时使用。",
                    not_for="不能审批、提交、启用策略或修改持仓。",
                    request_modes=("proposal",),
                    required_dependencies=("worker_result",),
                    accepted_dependencies=("worker_result",),
                    outputs=("proposal",),
                    supports_parallel=False,
                    side_effect_scope="proposal_only",
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=REPORT_COMPOSER,
            role=REPORT_COMPOSER,
            description="根据上游标准结果生成最终报告。",
            capabilities=[
                _capability(
                    "report.compose",
                    "compose_report",
                    "把全部相关专业结果汇总为最终回答。",
                    "专业分析任务完成后需要生成用户可读报告时使用。",
                    not_for="不重新读取原始数据，不新增事实或业务结论。",
                    required_dependencies=("worker_result",),
                    accepted_dependencies=("worker_result",),
                    outputs=("report_draft",),
                    supports_parallel=False,
                    can_finalize=True,
                    side_effect_scope="reasoning_only",
                ),
            ],
        ),
        AgentCapabilityCard(
            agent_id=SYSTEM_DIAGNOSTIC,
            role=SYSTEM_DIAGNOSTIC,
            description="检查当前金融图连接状态。",
            capabilities=[
                _capability(
                    "system.graph_diagnostic",
                    "diagnose_graph_system",
                    "检查当前金融图运行链路的连接状态。",
                    "用户明确询问金融图连接或可用状态时使用。",
                    not_for="不负责完整系统诊断、修复、配置修改或服务重启。",
                    request_modes=("analysis",),
                    outputs=("diagnostic_analysis",),
                ),
            ],
        ),
    ]


class AgentDirectory:
    """Index public capabilities and resolve their private Worker bindings."""

    def __init__(
        self,
        cards: list[AgentCapabilityCard] | None = None,
        *,
        required_outputs_by_mode: dict[str, Iterable[str]] | None = None,
    ) -> None:
        selected_cards = list(cards) if cards is not None else _default_cards()
        self._cards = {card.agent_id: card for card in selected_cards}
        if len(self._cards) != len(selected_cards):
            raise ValueError("duplicate_worker_id")

        self._capability_bindings: dict[
            str, tuple[AgentCapabilityCard, WorkerCapability]
        ] = {}
        for card in selected_cards:
            if len(card.capabilities) != 1:
                raise ValueError(
                    f"worker_card_requires_exactly_one_capability:{card.agent_id}"
                )
            for capability in card.capabilities:
                capability_id = str(capability.capability_id or "").strip()
                if not capability_id:
                    raise ValueError(f"empty_capability_id:{card.agent_id}")
                if capability_id in self._capability_bindings:
                    raise ValueError(f"duplicate_capability_id:{capability_id}")
                self._capability_bindings[capability_id] = (card, capability)

        policy = required_outputs_by_mode or {
            "analysis": ("report_draft",),
            "proposal": ("proposal", "report_draft"),
        }
        self._required_outputs_by_mode = {
            str(mode).strip().lower(): tuple(
                str(item).strip()
                for item in outputs
                if str(item).strip()
            )
            for mode, outputs in policy.items()
        }

    def get(self, agent_id: str) -> AgentCapabilityCard:
        key = str(agent_id or "").upper()
        if key not in self._cards:
            raise KeyError(f"unknown_worker_agent:{key}")
        return self._cards[key]

    def get_capability(self, capability_id: str) -> WorkerCapability:
        key = str(capability_id or "").strip()
        binding = self._capability_bindings.get(key)
        if binding is None:
            raise KeyError(f"unknown_worker_capability:{key}")
        return binding[1]

    def resolve(
        self,
        capability_id: str,
        *,
        request_mode: str = "",
    ) -> ResolvedWorkerCapability:
        key = str(capability_id or "").strip()
        binding = self._capability_bindings.get(key)
        if binding is None:
            raise KeyError(f"unknown_worker_capability:{key}")
        card, capability = binding
        mode = str(request_mode or "").strip().lower()
        if mode and mode not in set(capability.request_modes):
            raise ValueError(f"capability_not_available_for_mode:{key}:{mode}")
        return ResolvedWorkerCapability(
            capability_id=key,
            worker_id=card.agent_id,
            task_type=capability.task_type,
            required_dependency_output_types=tuple(
                capability.required_dependency_output_types
            ),
            accepted_dependency_output_types=tuple(
                capability.accepted_dependency_output_types
            ),
            produced_output_types=tuple(capability.produced_output_types),
            supports_parallel=capability.supports_parallel,
            can_finalize=capability.can_finalize,
            side_effect_scope=capability.side_effect_scope,
        )

    def list_cards(self) -> list[AgentCapabilityCard]:
        return list(self._cards.values())

    def safe_catalog(self) -> list[dict[str, Any]]:
        return [card.safe_for_coordinator() for card in self.list_cards()]

    def required_outputs_for_mode(self, request_mode: str) -> list[str]:
        mode = str(request_mode or "").strip().lower()
        if mode not in self._required_outputs_by_mode:
            raise KeyError(f"unsupported_agent_request_mode:{mode}")
        return list(self._required_outputs_by_mode[mode])

    def supports(self, agent_id: str, task_type: str) -> bool:
        try:
            card = self.get(agent_id)
        except KeyError:
            return False
        return str(task_type or "") in card.accepted_task_types

    def candidates_for(self, task_type: str) -> list[str]:
        task = str(task_type or "")
        return [
            card.agent_id
            for card in self.list_cards()
            if task in card.accepted_task_types
        ]


__all__ = [
    "AgentDirectory",
    "ResolvedWorkerCapability",
    "COORDINATOR",
    "EVIDENCE_RESEARCHER",
    "MARKET_ANALYST",
    "PORTFOLIO_ANALYST",
    "GRAPH_IMPACT_ANALYST",
    "PORTFOLIO_RISK_ANALYST",
    "STRATEGY_PROPOSAL_BUILDER",
    "REPORT_COMPOSER",
    "SYSTEM_DIAGNOSTIC",
]

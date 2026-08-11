"""Authoritative Worker implementation directory.

MainAgent receives every eligible Worker's complete public capability description upfront.
Private prompts and private Tool IDs never leave the Worker runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EVIDENCE_COLLECTOR = "EVIDENCE_COLLECTOR"
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
GRAPH_RELATION_RETRIEVER = "GRAPH_RELATION_RETRIEVER"
RISK_ANALYST = "RISK_ANALYST"
STRATEGY_GUARD = "STRATEGY_GUARD"
REPORT_WRITER = "REPORT_WRITER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"
DATABASE_WRITER = "DATABASE_WRITER"
ENTITY_ANALYST = "ENTITY_ANALYST"


@dataclass(frozen=True)
class CapabilityWorkerCard:
    worker_id: str
    agent_id: str
    role: str
    short_description: str
    full_description: str
    supported_boundary_ids: list[str]
    delegation_description: str = ""
    delegate_when: list[str] = field(default_factory=list)
    capability_tags: list[str] = field(default_factory=list)
    supported_scenarios: list[str] = field(default_factory=list)
    unsupported_scenarios: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    escalation_policy: str = ""
    execution_mode: str = "pure_llm"
    output_publication_mode: str = "worker_synthesized"
    max_effect_level: str = "read"
    private_worker_prompt: str = ""
    private_tool_ids: list[str] = field(default_factory=list)
    model_profile: str = ""
    availability: str = "available"


_CARDS = {
    "W01": CapabilityWorkerCard(
        worker_id="W01",
        agent_id=EVIDENCE_COLLECTOR,
        role="external_evidence_research",
        short_description="检索并整理目标实体相关的新闻、公告和RAG证据。",
        full_description=(
            "负责外部证据的检索、合并、去重、来源时间保留和业务为空表达。"
            "只产出可追溯证据，不形成最终金融判断，也不写入业务状态。"
        ),
        supported_boundary_ids=["external_evidence.research"],
        capability_tags=["news", "announcement", "rag", "evidence"],
        supported_scenarios=["实体新闻检索", "公告与研报证据收集", "证据去重与覆盖检查"],
        unsupported_scenarios=["最终实体分析", "风险评级", "状态变更"],
        limitations=["依赖已解析的权威实体槽位", "不补造不存在的证据"],
        escalation_policy="私有Tool重试或替换仍无法形成证据槽位时上报MainAgent。",
        execution_mode="hybrid",
        private_worker_prompt="根据合同列表选择最小私有Tool DAG，收集可追溯外部证据；不得分析或写入。",
        private_tool_ids=["evidence.search_news", "evidence.search_rag", "evidence.finalize_collection"],
    ),
    "W02": CapabilityWorkerCard(
        worker_id="W02",
        agent_id=PORTFOLIO_ANALYST,
        role="system_internal_fact_provider",
        short_description="读取本系统内部产生或保存的权威数据，并发布为结构化信息Slot。",
        full_description=(
            "W02是系统内部权威数据提供者。它从本应用自己的只读数据源读取模型预测、评分/排名、"
            "模型质量、回测摘要、当前选定策略、账户、组合、持仓、用户画像和约束，并发布标准信息Slot。"
            "它可根据MainAgent下发的业务目标，自主规划私有Tool DAG：既可直接读取已知实体的内部信号，也可先读取全市场排名、"
            "再通过权威实体解析确定目标后继续读取相关内部事实。它不负责最终实体分析或自然语言报告；下游Worker可消费这些Slot继续分析。"
        ),
        supported_boundary_ids=["internal_fact.retrieval", "portfolio.analysis", "user_context.retrieval"],
        delegation_description=(
            "当用户问题需要引用本系统内部已有或本系统自己生成的权威数据时，考虑委派W02。"
            "这包括但不限于模型预测/评分、市场排名、模型指标、回测、选定策略、账户、组合、持仓、"
            "用户画像或约束；W02只读取并发布结构化事实Slot，可作为其他分析Worker的上游数据源。"
        ),
        delegate_when=[
            "回答需要本系统自己的模型、评分、排名、回测或策略状态",
            "回答需要本系统保存的账户、组合、持仓、画像或约束",
            "其他Worker的分析目标可以直接消费系统内部权威事实Slot",
        ],
        capability_tags=[
            "system_data", "internal_fact", "prediction", "ranking", "model_metrics",
            "backtest", "strategy_state", "portfolio", "account", "profile",
        ],
        supported_scenarios=[
            "系统内部模型信号读取", "全市场排名后自主定位目标实体", "评分与排名读取", "模型质量与回测读取",
            "当前策略状态读取", "当前组合与持仓读取", "账户与用户约束读取",
        ],
        unsupported_scenarios=["外部新闻研究", "最终报告写作", "业务写入"],
        limitations=["只读取内部权威数据", "不把读取结果自行扩展成最终业务结论"],
        escalation_policy="私有Tool均无法产出合同槽位时上报MainAgent。",
        execution_mode="hybrid",
        output_publication_mode="private_tool_passthrough",
        private_worker_prompt=(
            "根据MainAgent给出的业务目标和合同承诺Slot，自主规划最小私有Tool DAG。"
            "只有当业务目标本身是全市场排名、筛选或发现候选证券时，才允许先读取排名并通过"
            "internal.entity.resolve_ranked_security把排名结果解析成GraphRef后继续调用实体Tool。"
            "如果业务目标明确指向某个命名证券/公司，而available_context没有该目标的权威security_node_id/GraphRef，"
            "绝不能用排名第一或其他候选证券替代目标；此时实体特定输出应保持缺失并按现有失败合同上报。"
            "只发布结构化内部事实，不做最终分析或报告。"
        ),
        private_tool_ids=[
            "internal.prediction.get_stock", "internal.ranking.get_latest",
            "internal.entity.resolve_ranked_security",
            "internal.model.get_metrics", "internal.backtest.get_summary",
            "internal.strategy.get_selected", "internal.portfolio.get_state",
            "internal.account.get_state", "internal.user_profile.get",
        ],
    ),
    "W03": CapabilityWorkerCard(
        worker_id="W03",
        agent_id=GRAPH_RELATION_RETRIEVER,
        role="graph_relation_retrieval",
        short_description="根据已绑定GraphRef槽位读取邻域关系、关联事实和可追溯路径。",
        full_description=(
            "负责在锁定GraphRef范围内读取金融图关系。Tool可用性只由required_input_slots决定，"
            "不得根据实体数量猜测邻域或路径查询。"
        ),
        supported_boundary_ids=["graph_relation.retrieval"],
        capability_tags=["graph", "relation", "neighborhood", "path"],
        supported_scenarios=["实体邻域关系读取", "显式来源与目标之间的路径读取"],
        unsupported_scenarios=["创建实体", "最终业务解释", "图数据库写入"],
        limitations=["关系端点必须来自权威GraphRef", "不推断未绑定的来源或目标角色"],
        escalation_policy="无兼容私有Tool或局部处理耗尽后上报MainAgent。",
        execution_mode="hybrid",
        output_publication_mode="private_tool_passthrough",
        private_worker_prompt=(
            "只在锁定GraphRef范围内读取关系，不创造实体。不得按实体数量决定工具；"
            "先按required_input_slots过滤，再结合合同目标、Tool摘要和produced_outputs规划。"
        ),
        private_tool_ids=["graph.relations.read_neighborhood", "graph.relations.find_paths"],
    ),
    "W04": CapabilityWorkerCard(
        worker_id="W04",
        agent_id=RISK_ANALYST,
        role="portfolio_risk_assessment",
        short_description="消费本任务已绑定的组合、账户、用户约束等风险相关Slot，计算风险事实并形成风险评估。",
        full_description=(
            "负责基于CapabilityContract实际绑定的权威业务Slot完成集中度、暴露、账户风险事实和约束审查，不修改持仓。"
            "W04依赖的是本轮所需的信息Slot，而不是固定依赖某个Worker；如果完成风险任务所需的业务Slot没有绑定，"
            "应向MainAgent上报缺失信息，由MainAgent决定增加上游能力、补充上下文，或在确认属于用户参数时再询问用户。"
        ),
        supported_boundary_ids=["portfolio.risk_assessment", "context.resolution"],
        delegation_description=(
            "当用户目标需要对已经取得的组合、账户、持仓、用户约束或其他风险相关事实做集中度、暴露和风险边界分析时委派W04。"
            "W04不负责假设或补造未绑定的业务事实；缺少所需Slot时只向MainAgent报告缺口。"
        ),
        delegate_when=[
            "需要基于已绑定组合或账户事实计算集中度、暴露或风险边界",
            "需要审查已绑定用户约束与当前组合之间的风险关系",
            "下游调仓或方案Worker需要结构化风险分析Slot作为依据",
        ],
        capability_tags=["risk", "concentration", "exposure", "constraint"],
        supported_scenarios=["组合集中度分析", "账户风险事实分析", "风险约束审查", "为下游方案提供结构化风险Slot"],
        unsupported_scenarios=["读取未绑定的原始业务事实", "订单执行", "持仓写入", "最终调仓Proposal生成"],
        limitations=["只消费本轮CapabilityContract绑定的业务Slot", "不与任何特定上游Worker ID硬绑定"],
        escalation_policy="所需业务Slot未绑定或私有Tool无法完成时，先向MainAgent上报缺失信息；W04不直接向用户索取内部业务对象。",
        execution_mode="hybrid",
        private_worker_prompt="根据风险合同和已绑定Slot选择最小只读Tool DAG，区分风险事实和建议；缺少合同必需Slot时上报MainAgent，不补造输入。",
        private_tool_ids=[
            "risk.calculate_concentration", "risk.read_account_risk_facts",
            "risk.summarize_exposure", "risk.finalize_facts",
        ],
    ),
    "W05": CapabilityWorkerCard(
        worker_id="W05",
        agent_id=STRATEGY_GUARD,
        role="state_change_proposal",
        short_description="消费本轮已绑定的状态、约束、风险分析等Slot，生成或审查需要用户审批的状态变更Proposal。",
        full_description=(
            "只基于CapabilityContract实际绑定的上游事实与分析Slot生成和审查待审批方案，不执行Commit，不绕过审批。"
            "调仓场景可以消费W04等上游能力产生的风险Slot，但W05不与W04或任何特定Worker ID硬绑定；是否需要风险分析由本轮合同决定。"
        ),
        supported_boundary_ids=["state_change.proposal"],
        delegation_description=(
            "当用户明确要求形成调仓、配置调整或其他状态变更方案时委派W05。"
            "W05根据本轮已绑定的组合状态、用户约束、风险分析或其他必要Slot形成待审批Proposal。"
        ),
        delegate_when=["存在明确的调仓或状态变更意图", "需要把已验证的上游事实/风险结论转成待审批Proposal"],
        capability_tags=["proposal", "approval", "strategy_guard"],
        supported_scenarios=["调仓方案生成", "状态变更约束审查", "消费上游风险分析形成Proposal"],
        unsupported_scenarios=["直接Commit", "绕过审批", "替代上游专业风险分析"],
        limitations=["必须存在显式变更意图", "只消费本轮合同绑定的Slot，不固定依赖某个Worker"],
        escalation_policy="缺少形成合规Proposal所需的已验证Slot时上报MainAgent；只有MainAgent确认属于用户参数后才询问用户。",
        execution_mode="pure_llm",
        max_effect_level="proposal",
        private_worker_prompt="只生成或审查待审批Proposal，不得Commit。",
    ),
    "W06": CapabilityWorkerCard(
        worker_id="W06",
        agent_id=REPORT_WRITER,
        role="result_composition",
        short_description="把已验证的上游槽位组织为用户可读报告。",
        full_description="负责把已绑定的结构化结果转换为用户自然语言，只保留输入中已经存在的不确定性，不重新查询、不补充专业事实，也不评价未提供的信息域。",
        supported_boundary_ids=["result.composition"],
        capability_tags=["report", "composition", "response"],
        supported_scenarios=["分析报告汇总", "诊断报告汇总", "Proposal说明"],
        unsupported_scenarios=["重新检索数据", "新增金融判断"],
        limitations=["只能使用已验证上游槽位"],
        escalation_policy="缺少必需上游槽位时上报MainAgent。",
        execution_mode="pure_llm",
        private_worker_prompt="只把已验证上游槽位转换为自然语言，不重新查询、不新增专业事实、不评价未提供的信息域。",
    ),
    "W07": CapabilityWorkerCard(
        worker_id="W07",
        agent_id=SYSTEM_DIAGNOSTIC,
        role="system_diagnosis",
        short_description="诊断参数、上下文、工具、业务为空和运行时问题。",
        full_description="负责区分参数缺失、上下文缺失、工具失败、业务为空和业务不足。",
        supported_boundary_ids=["system.diagnosis", "context.resolution"],
        capability_tags=["diagnosis", "runtime", "context"],
        supported_scenarios=["运行失败诊断", "上下文问题诊断"],
        unsupported_scenarios=["金融研究", "业务写入"],
        limitations=["不替代专业业务Worker"],
        escalation_policy="诊断无法确认时明确返回未知，不猜测。",
        execution_mode="pure_llm",
        private_worker_prompt="严格区分调用参数缺失、上下文缺失、工具失败、业务为空和业务不足。",
    ),
    "W08": CapabilityWorkerCard(
        worker_id="W08",
        agent_id=DATABASE_WRITER,
        role="graph_context_write",
        short_description="将已验证的非交易结果幂等写入金融图上下文。",
        full_description="只执行已验证的非交易图上下文写入，保持权限、幂等和审计。",
        supported_boundary_ids=["graph_context.write"],
        capability_tags=["graph_write", "idempotent", "audit"],
        supported_scenarios=["组合图上下文写入", "证据图上下文写入"],
        unsupported_scenarios=["交易下单", "任意数据库写入"],
        limitations=["需要显式写合同和权限"],
        escalation_policy="权限或输入不满足时拒绝并上报MainAgent。",
        execution_mode="workflow_backed",
        max_effect_level="write",
        private_worker_prompt="只执行已验证的非交易图上下文写入，保持幂等和审计。",
        private_tool_ids=["database.write_portfolio_graph_context", "database.write_evidence_graph_context"],
    ),
    "W09": CapabilityWorkerCard(
        worker_id="W09",
        agent_id=ENTITY_ANALYST,
        role="entity_analysis",
        short_description="基于本任务实际绑定的信息Slot形成结构化实体分析。",
        full_description=(
            "以Slot为唯一上游接口，只处理当前CapabilityContract实际绑定并由SlotBinder提供的信息。"
            "Worker不得比较本次输入与未分配的能力或信息域，也不得自行扩大输入要求。"
            "不重新查询数据。"
        ),
        supported_boundary_ids=["entity.analysis"],
        capability_tags=["entity_analysis", "synthesis", "uncertainty"],
        supported_scenarios=["个股综合分析", "多实体结构化分析"],
        unsupported_scenarios=["自行检索证据", "状态变更"],
        limitations=["必需输入由合同决定", "结论必须回溯上游槽位"],
        escalation_policy="必需Slot缺失时上报MainAgent，不向用户索取内部类型对象。",
        execution_mode="pure_llm",
        private_worker_prompt="只融合已绑定Slot，输出通用facts、analysis、uncertainties和conclusion，不感知未绑定信息域。",
    ),
}


class CapabilityWorkerDirectory:
    def __init__(self) -> None:
        self._cards = dict(_CARDS)

    def get(self, identifier: str) -> CapabilityWorkerCard:
        key = str(identifier or "").strip().upper()
        if key in self._cards:
            return self._cards[key]
        for card in self._cards.values():
            if card.agent_id == key:
                return card
        raise KeyError(f"unknown_capability_worker:{identifier}")

    def list(self) -> list[CapabilityWorkerCard]:
        return [self._cards[key] for key in sorted(self._cards)]

    def private_tool_ids(self, worker_id: str) -> list[str]:
        return list(self.get(worker_id).private_tool_ids)

    def private_prompt(self, worker_id: str) -> str:
        return str(self.get(worker_id).private_worker_prompt)


__all__ = [
    "CapabilityWorkerCard", "CapabilityWorkerDirectory", "DATABASE_WRITER",
    "ENTITY_ANALYST", "EVIDENCE_COLLECTOR", "GRAPH_RELATION_RETRIEVER",
    "PORTFOLIO_ANALYST", "REPORT_WRITER", "RISK_ANALYST", "STRATEGY_GUARD",
    "SYSTEM_DIAGNOSTIC",
]

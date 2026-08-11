from __future__ import annotations

from typing import Any

from .models import CapabilityBoundary


# MainAgent-visible rule vocabulary. Runtime owns the checks. Capability-level
# schema validation is intentionally generic: concrete business tasks do not
# register one new Pydantic schema per Slot.
ACCEPTANCE_RULES: dict[str, str] = {
    "schema_valid": "输出必须是已物化的通用Slot，并满足合同声明的required_paths。",
    "entity_scope_consistent": "输出实体范围必须与锁定 GraphRef 一致。",
    "provenance_present": "业务事实必须保留来源引用。",
    "freshness_satisfied": "数据时间必须满足任务的新鲜度要求。",
    "no_forbidden_output": "不得产生合同禁止的信息槽位。",
    "business_empty_explicit": "查询成功但无记录时必须明确标记业务为空。",
    "failure_kind_classified": "参数、上下文、工具、业务为空和业务不足必须分类。",
    "facts_and_analysis_separated": "事实与分析必须结构化分离。",
    "claims_traceable": "专业结论必须能回溯到上游结果。",
    "uncertainty_explicit": "必须表达不确定性和局限。",
    "source_dates_preserved": "证据的来源时间必须保留。",
    "no_new_business_claims": "不得增加上游不存在的业务事实。",
    "proposal_requires_approval": "状态变更方案必须明确需要审批。",
    "no_persistent_write": "当前能力不得持久化修改业务状态。",
    "goal_coverage": "输出必须覆盖当前任务目标。",
}


def _boundary(
    *,
    boundary_id: str,
    name: str,
    description: str,
    responsibilities: list[str],
    non_responsibilities: list[str],
    accepted_input_patterns: list[str],
    produced_output_patterns: list[str],
    input_slot_examples: list[str],
    output_slot_examples: list[str],
    allowed_acceptance_rule_ids: list[str],
    required_context_slots: list[str] | None = None,
    allowed_information_sources: list[str] | None = None,
    max_effect_level: str = "read",
    completion_principles: list[str] | None = None,
) -> CapabilityBoundary:
    return CapabilityBoundary(
        boundary_id=boundary_id,
        name=name,
        description=description,
        responsibilities=responsibilities,
        non_responsibilities=non_responsibilities,
        accepted_input_patterns=accepted_input_patterns,
        produced_output_patterns=produced_output_patterns,
        input_slot_examples=input_slot_examples,
        output_slot_examples=output_slot_examples,
        allowed_acceptance_rule_ids=allowed_acceptance_rule_ids,
        required_context_slots=list(required_context_slots or []),
        allowed_information_sources=list(allowed_information_sources or []),
        max_effect_level=max_effect_level,
        completion_principles=list(completion_principles or []),
    )


_BOUNDARIES: dict[str, CapabilityBoundary] = {
    "external_evidence.research": _boundary(
        boundary_id="external_evidence.research",
        name="外部证据研究",
        description="检索、整理并去重目标实体相关的新闻、公告和研究证据；entity_external_evidence 是面向下游分析的紧凑统一主证据集合，完整 Tool 结果不跨 Worker 传输；evidence_source_records 是轻量溯源索引，evidence.* 是按来源的可选视图。",
        responsibilities=["收集外部证据", "形成统一主证据集合", "按需发布来源视图和溯源索引", "保留来源和时间", "明确业务为空"],
        non_responsibilities=["解释最终含义", "生成风险评级", "生成操作方案"],
        accepted_input_patterns=["authoritative_entity_refs", "current_user_request", "as_of_time", "entity.*", "request.*", "time.*"],
        produced_output_patterns=["evidence.*", "entity_external_evidence", "evidence_source_records"],
        input_slot_examples=["authoritative_entity_refs", "current_user_request", "as_of_time"],
        output_slot_examples=["entity_external_evidence", "evidence_source_records", "evidence.news", "evidence.research"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "provenance_present", "source_dates_preserved", "business_empty_explicit", "no_persistent_write"],
        required_context_slots=["authoritative_entity_refs"],
        allowed_information_sources=["registered_external_evidence_tools"],
        completion_principles=["证据可追溯", "不得补造", "按实体去重", "跨 Worker 只传分析所需的单份标准化正文与必要 provenance", "output_slot_examples 是可选语义输出，不要求同一任务全部发布"],
    ),
    "internal_fact.retrieval": _boundary(
        boundary_id="internal_fact.retrieval",
        name="内部权威事实读取",
        description="读取预测、排名、指标、回测和策略等系统内部结构化事实。",
        responsibilities=["读取内部事实", "保留数据日期", "返回标准化槽位"],
        non_responsibilities=["检索外部新闻", "替代专业分析", "修改业务状态"],
        accepted_input_patterns=["authoritative_entity_refs", "user_identity", "current_user_request", "as_of_time", "business_parameters", "entity.*", "request.*", "state.*"],
        produced_output_patterns=["entity.*", "ranking.*", "metric.*", "backtest.*", "strategy.*", "state.*", "entity_model_signals", "market_ranking_signals", "model_quality_metrics", "backtest_summary", "selected_strategy_state"],
        input_slot_examples=["authoritative_entity_refs", "user_identity", "current_user_request", "business_parameters"],
        output_slot_examples=["entity_model_signals", "market_ranking_signals", "model_quality_metrics", "backtest_summary", "selected_strategy_state"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "provenance_present", "freshness_satisfied", "business_empty_explicit", "failure_kind_classified", "no_persistent_write"],
        allowed_information_sources=["registered_internal_read_tools"],
        completion_principles=["只返回真实记录", "业务为空与工具失败分离"],
    ),
    "portfolio.analysis": _boundary(
        boundary_id="portfolio.analysis",
        name="组合结构分析",
        description="读取并描述当前账户组合、持仓和资产结构。",
        responsibilities=["读取组合状态", "返回持仓与资产结构事实"],
        non_responsibilities=["风险评级", "调仓方案", "修改账户状态"],
        accepted_input_patterns=["user_identity", "permission_context", "as_of_time", "user.*", "permission.*", "time.*"],
        produced_output_patterns=["state.*", "portfolio.*", "current_portfolio_state", "portfolio_positions"],
        input_slot_examples=["user_identity", "permission_context", "as_of_time"],
        output_slot_examples=["current_portfolio_state", "portfolio_positions", "state.portfolio", "state.positions"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "provenance_present", "business_empty_explicit", "no_persistent_write"],
        required_context_slots=["user_identity"],
        allowed_information_sources=["registered_portfolio_read_tools"],
        completion_principles=["覆盖当前有效持仓", "使用权威用户身份"],
    ),
    "user_context.retrieval": _boundary(
        boundary_id="user_context.retrieval",
        name="用户上下文读取",
        description="读取账户资金、用户画像和业务约束。",
        responsibilities=["读取账户状态", "读取用户画像和约束"],
        non_responsibilities=["修改画像", "修改资金", "生成最终策略"],
        accepted_input_patterns=["user_identity", "permission_context", "as_of_time", "user.*", "permission.*", "time.*"],
        produced_output_patterns=["state.*", "profile.*", "constraint.*", "account_financial_state", "user_profile_state", "user_constraints"],
        input_slot_examples=["user_identity", "permission_context", "as_of_time"],
        output_slot_examples=["account_financial_state", "user_profile_state", "user_constraints", "state.account", "profile.user", "constraint.user"],
        allowed_acceptance_rule_ids=["schema_valid", "provenance_present", "business_empty_explicit", "failure_kind_classified", "no_persistent_write"],
        required_context_slots=["user_identity"],
        allowed_information_sources=["registered_user_context_read_tools"],
        completion_principles=["只读取当前用户", "缺失记录明确返回"],
    ),
    "graph_relation.retrieval": _boundary(
        boundary_id="graph_relation.retrieval",
        name="金融关系检索",
        description="在锁定 GraphRef 范围内检索实体关系和路径。",
        responsibilities=["读取关系路径", "返回图关系事实"],
        non_responsibilities=["自行创造实体", "形成最终判断", "写入图数据库"],
        accepted_input_patterns=["authoritative_entity_refs", "source_entity_refs", "target_entity_refs", "current_user_request", "as_of_time", "entity.*", "request.*"],
        produced_output_patterns=["graph.*", "relation.*", "financial_relation_paths", "graph_relation_facts"],
        input_slot_examples=["authoritative_entity_refs", "source_entity_refs", "target_entity_refs"],
        output_slot_examples=["financial_relation_paths", "graph_relation_facts", "relation.paths", "graph.facts"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "provenance_present", "no_persistent_write"],
        required_context_slots=["authoritative_entity_refs"],
        allowed_information_sources=["registered_graph_read_tools"],
        completion_principles=["关系端点来自权威 GraphRef", "路径可追溯"],
    ),
    "entity.analysis": _boundary(
        boundary_id="entity.analysis",
        name="金融实体分析",
        description="基于上游证据和内部事实形成结构化实体分析；存在 entity_external_evidence 时优先消费统一主证据，避免把同源 evidence.* 派生视图重复送入分析。",
        responsibilities=["区分事实与分析", "优先消费统一主证据而非重复派生视图", "解释模型信号", "表达不确定性"],
        non_responsibilities=["自行检索证据", "生成交易方案", "提交业务写入"],
        accepted_input_patterns=["authoritative_entity_refs", "entity.*", "evidence.*", "ranking.*", "metric.*", "graph.*", "relation.*", "entity_external_evidence", "evidence_source_records", "entity_model_signals", "market_ranking_signals", "model_quality_metrics", "financial_relation_paths", "graph_relation_facts"],
        produced_output_patterns=["analysis.*", "entity_analysis", "entity_analysis_uncertainty"],
        input_slot_examples=["entity_external_evidence", "entity_model_signals", "financial_relation_paths"],
        output_slot_examples=["entity_analysis", "entity_analysis_uncertainty", "analysis.entity"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "facts_and_analysis_separated", "claims_traceable", "uncertainty_explicit", "no_new_business_claims", "no_persistent_write"],
        allowed_information_sources=["verified_upstream_slots"],
        completion_principles=["结论可回溯", "事实与判断分离"],
    ),
    "portfolio.risk_assessment": _boundary(
        boundary_id="portfolio.risk_assessment",
        name="组合风险评估",
        description="基于组合状态和用户约束评估集中度、暴露和风险边界。",
        responsibilities=["计算风险事实", "审查风险约束", "结构化风险结论"],
        non_responsibilities=["修改持仓", "执行订单", "绕过 Proposal 审批"],
        accepted_input_patterns=["state.*", "portfolio.*", "profile.*", "constraint.*", "ranking.*", "current_portfolio_state", "portfolio_positions", "account_financial_state", "user_profile_state", "user_constraints", "market_ranking_signals"],
        produced_output_patterns=["risk.*", "analysis.risk*", "constraint.risk*", "portfolio_risk_result", "risk_constraint_review"],
        input_slot_examples=["current_portfolio_state", "portfolio_positions", "user_constraints"],
        output_slot_examples=["portfolio_risk_result", "risk_constraint_review", "analysis.risk", "constraint.risk"],
        allowed_acceptance_rule_ids=["schema_valid", "provenance_present", "claims_traceable", "failure_kind_classified", "no_persistent_write"],
        allowed_information_sources=["verified_upstream_slots", "registered_risk_tools"],
        completion_principles=["风险事实与建议分离", "不把业务为空当工具失败"],
    ),
    "state_change.proposal": _boundary(
        boundary_id="state_change.proposal",
        name="状态变更方案",
        description="根据显式变更目标生成待审批 Proposal，不直接提交。",
        responsibilities=["生成待审批方案", "审查约束", "声明审批边界"],
        non_responsibilities=["直接 Commit", "绕过 Approval", "修改持仓或资金"],
        accepted_input_patterns=["state.*", "portfolio.*", "profile.*", "constraint.*", "risk.*", "analysis.*", "ranking.*", "strategy.*", "current_portfolio_state", "portfolio_positions", "account_financial_state", "user_profile_state", "user_constraints", "portfolio_risk_result", "risk_constraint_review", "market_ranking_signals", "selected_strategy_state", "entity_analysis"],
        produced_output_patterns=["proposal.*", "reviewed_proposal"],
        input_slot_examples=["current_portfolio_state", "portfolio_positions", "user_constraints", "portfolio_risk_result"],
        output_slot_examples=["reviewed_proposal", "proposal.rebalance"],
        allowed_acceptance_rule_ids=["schema_valid", "claims_traceable", "proposal_requires_approval", "no_persistent_write", "goal_coverage"],
        max_effect_level="proposal",
        allowed_information_sources=["verified_upstream_slots"],
        completion_principles=["显式变更意图", "Proposal 与 Commit 分离"],
    ),
    "result.composition": _boundary(
        boundary_id="result.composition",
        name="结果汇总",
        description="把终端专业结果组织成用户可读报告。",
        responsibilities=["组织自然语言", "保留来源任务", "表达局限"],
        non_responsibilities=["重新查询数据", "新增专业判断", "修改上游结论"],
        accepted_input_patterns=["*"],
        produced_output_patterns=["result.*", "report.*", "user_facing_report", "goal_completion_summary"],
        input_slot_examples=["entity_analysis", "portfolio_risk_result", "reviewed_proposal"],
        output_slot_examples=["user_facing_report", "goal_completion_summary", "result.user_facing"],
        allowed_acceptance_rule_ids=["schema_valid", "claims_traceable", "uncertainty_explicit", "no_new_business_claims", "goal_coverage", "no_persistent_write"],
        allowed_information_sources=["verified_upstream_slots"],
        completion_principles=["不新增上游没有的结论", "保留局限"],
    ),
    "system.diagnosis": _boundary(
        boundary_id="system.diagnosis",
        name="系统诊断",
        description="诊断运行时、工具、参数、上下文和业务结果问题。",
        responsibilities=["区分失败类型", "检查运行状态", "输出诊断结论"],
        non_responsibilities=["金融研究", "交易方案", "修改业务状态"],
        accepted_input_patterns=["runtime_context", "current_user_request", "session_summary", "runtime.*", "request.*", "context.*"],
        produced_output_patterns=["diagnostic.*", "runtime.*", "system_diagnosis", "runtime_status"],
        input_slot_examples=["runtime_context", "current_user_request", "session_summary"],
        output_slot_examples=["system_diagnosis", "runtime_status", "diagnostic.runtime"],
        allowed_acceptance_rule_ids=["schema_valid", "failure_kind_classified", "no_persistent_write"],
        allowed_information_sources=["runtime_context", "registered_diagnostic_tools"],
        completion_principles=["严格区分失败类型"],
    ),
    "context.resolution": _boundary(
        boundary_id="context.resolution",
        name="上下文补齐",
        description="在已知边界内补齐被阻塞任务需要的可验证上下文。",
        responsibilities=["读取可验证上下文", "发布标准上下文槽位"],
        non_responsibilities=["猜测用户参数", "绕过权限", "修改业务状态"],
        accepted_input_patterns=["runtime_context", "session_summary", "user_identity", "runtime.*", "context.*", "user.*"],
        produced_output_patterns=["context.*", "resolved_context"],
        input_slot_examples=["runtime_context", "session_summary", "user_identity"],
        output_slot_examples=["resolved_context", "context.resolved"],
        allowed_acceptance_rule_ids=["schema_valid", "provenance_present", "failure_kind_classified", "no_persistent_write"],
        allowed_information_sources=["runtime_context", "verified_memory"],
        completion_principles=["只补齐可验证上下文"],
    ),
    "graph_context.write": _boundary(
        boundary_id="graph_context.write",
        name="图上下文写入",
        description="将已验证结果幂等写入非交易性图上下文。",
        responsibilities=["非交易性图上下文写入"],
        non_responsibilities=["交易下单", "绕过权限", "任意数据库写入"],
        accepted_input_patterns=["state.*", "portfolio.*", "evidence.*", "permission.*", "current_portfolio_state", "portfolio_positions", "entity_external_evidence", "evidence_source_records", "permission_context"],
        produced_output_patterns=["graph_context.*", "portfolio_graph_context", "evidence_graph_context"],
        input_slot_examples=["current_portfolio_state", "entity_external_evidence", "permission_context"],
        output_slot_examples=["portfolio_graph_context", "evidence_graph_context", "graph_context.portfolio"],
        allowed_acceptance_rule_ids=["schema_valid", "entity_scope_consistent", "provenance_present"],
        max_effect_level="write",
        allowed_information_sources=["validated_upstream_slots"],
        completion_principles=["显式写合同", "权限校验", "幂等审计"],
    ),
}


class CapabilityRegistry:
    """Business-boundary registry with open semantic-slot families."""

    def __init__(self, directory: Any | None = None) -> None:
        del directory
        self._boundaries = dict(_BOUNDARIES)

    def get_boundary(self, boundary_id: str) -> CapabilityBoundary:
        key = str(boundary_id or "").strip()
        if key not in self._boundaries:
            raise KeyError(f"unknown_capability_boundary:{key}")
        return self._boundaries[key]

    def aggregate_scope(self, boundary_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
        """Merge existing boundary definitions into one Worker-level capability scope.

        The existing boundary registry remains the source of truth for semantic
        Slot patterns and acceptance rules.  MainAgent no longer selects one of
        these fine-grained boundaries; Runtime uses their union only to validate
        the owning Worker's overall professional scope.
        """

        boundaries = [self.get_boundary(str(boundary_id)) for boundary_id in boundary_ids]
        if not boundaries:
            raise KeyError("empty_worker_capability_scope")

        def merge(name: str) -> list[str]:
            return list(dict.fromkeys(
                str(item)
                for boundary in boundaries
                for item in getattr(boundary, name, []) or []
                if str(item)
            ))

        return {
            "source_boundary_ids": [boundary.boundary_id for boundary in boundaries],
            "accepted_input_patterns": merge("accepted_input_patterns"),
            "produced_output_patterns": merge("produced_output_patterns"),
            "input_slot_examples": merge("input_slot_examples"),
            "output_slot_examples": merge("output_slot_examples"),
            "allowed_acceptance_rule_ids": merge("allowed_acceptance_rule_ids"),
            "required_context_slots": merge("required_context_slots"),
            "allowed_information_sources": merge("allowed_information_sources"),
            "completion_principles": merge("completion_principles"),
        }

    def public_catalog(
        self,
        *,
        request_mode: str,
        boundary_ids: list[str] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        mode = str(request_mode or "analysis").lower()
        maximum = "proposal" if mode == "proposal" else "read"
        order = {"read": 0, "proposal": 1, "write": 2}
        allowed = {str(item) for item in (boundary_ids or []) if str(item)}
        rows: list[dict[str, Any]] = []
        for boundary_id, boundary in sorted(self._boundaries.items()):
            if allowed and boundary_id not in allowed:
                continue
            if order.get(boundary.max_effect_level, 99) > order[maximum]:
                continue
            row = boundary.safe_for_main_agent()
            row["acceptance_rules"] = {
                rule_id: ACCEPTANCE_RULES[rule_id]
                for rule_id in boundary.allowed_acceptance_rule_ids
                if rule_id in ACCEPTANCE_RULES
            }
            rows.append(row)
        return rows

    def acceptance_rule_exists(self, rule_id: str) -> bool:
        return str(rule_id or "") in ACCEPTANCE_RULES

    def acceptance_rule_description(self, rule_id: str) -> str:
        return str(ACCEPTANCE_RULES.get(str(rule_id or ""), ""))


__all__ = ["ACCEPTANCE_RULES", "CapabilityRegistry"]

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import (
    AgentCapabilityCard,
    GraphAgentTask,
    GraphWorkerResult,
    WorkerTaskContract,
)
from .worker_contracts import (
    WorkerContractViolation,
    array_schema,
    object_schema,
    string_schema,
    validate_schema,
    worker_result_schema,
)


COORDINATOR = "COORDINATOR"
EVIDENCE_RETRIEVER = "EVIDENCE_RETRIEVER"
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
GRAPH_IMPACT_ANALYST = "GRAPH_IMPACT_ANALYST"
RISK_ANALYST = "RISK_ANALYST"
STRATEGY_GUARD = "STRATEGY_GUARD"
REPORT_WRITER = "REPORT_WRITER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"

W01 = "W01"
W02 = "W02"
W03 = "W03"
W04 = "W04"
W05 = "W05"
W06 = "W06"
W07 = "W07"


# Information-slot semantics used by goal-constrained forward planning.
#
# These declarations are business-capability metadata, not a fixed Worker chain.
# MainAgent starts from the context and information already available, enumerates
# task contracts whose requirements are currently satisfiable, and selects only
# tasks that contribute to still-unmet GoalContract slots or unlock a necessary
# downstream capability.
_FORWARD_TASK_SEMANTICS: dict[tuple[str, str], dict[str, Any]] = {
    (W01, "retrieve_evidence"): {
        "consumes_information_slots": ["authoritative_financial_entities", "research_question"],
        "produces_information_slots": ["entity_external_evidence", "evidence_source_refs"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "focus_entities", "partial_results_allowed": True},
        "freshness_semantics": {"policy": "respect_requested_time_range_or_latest"},
        "authority_level": "external_evidence_with_source_refs",
    },
    (W01, "analyze_entity_evidence"): {
        "consumes_information_slots": ["authoritative_financial_entities", "research_question"],
        "produces_information_slots": ["entity_evidence_analysis", "evidence_uncertainty"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "focus_entities", "claims_require_evidence_refs": True},
        "freshness_semantics": {"policy": "respect_requested_time_range_or_latest"},
        "authority_level": "evidence_grounded_analysis",
    },
    (W01, "compare_entity_evidence"): {
        "consumes_information_slots": ["multiple_authoritative_financial_entities", "research_question"],
        "produces_information_slots": ["comparative_entity_evidence", "comparison_evidence_refs"],
        "required_context_slots": ["multiple_authoritative_financial_entities"],
        "coverage_semantics": {"scope": "all_comparison_entities", "minimum_entities": 2},
        "freshness_semantics": {"policy": "same_requested_time_window"},
        "authority_level": "external_evidence_with_source_refs",
    },
    (W01, "ingest_evidence"): {
        "consumes_information_slots": ["authoritative_financial_entities", "research_question"],
        "produces_information_slots": ["entity_external_evidence", "derived_evidence_graph_state"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "focus_entities", "write_scope": "derived_evidence_only"},
        "freshness_semantics": {"policy": "refresh_requested_range"},
        "authority_level": "derived_evidence_graph",
    },
    (W01, "resolve_context"): {
        "consumes_information_slots": ["partial_evidence_context", "research_question"],
        "produces_information_slots": ["resolved_evidence_context", "entity_external_evidence"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "missing_evidence_context", "may_return_need_context": True},
        "freshness_semantics": {"policy": "preserve_requested_as_of_time"},
        "authority_level": "evidence_context_resolution",
    },
    (W02, "query_stock_prediction"): {
        "consumes_information_slots": ["authoritative_security_entities"],
        "produces_information_slots": ["entity_model_signals"],
        "required_context_slots": ["authoritative_security_entities"],
        "coverage_semantics": {"scope": "explicit_security_entities", "report_missing_entities": True},
        "freshness_semantics": {"policy": "requested_trade_date_or_latest"},
        "authority_level": "internal_model_store",
    },
    (W02, "query_latest_ranking"): {
        "consumes_information_slots": [],
        "produces_information_slots": ["market_ranking_signals"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "top_k_cross_section", "guarantees_focus_entity_coverage": False},
        "freshness_semantics": {"policy": "latest_available_ranking"},
        "authority_level": "internal_model_store",
    },
    (W02, "query_model_metrics"): {
        "consumes_information_slots": [],
        "produces_information_slots": ["model_quality_metrics"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "selected_or_active_model"},
        "freshness_semantics": {"policy": "latest_saved_metrics"},
        "authority_level": "internal_model_registry",
    },
    (W02, "query_backtest_summary"): {
        "consumes_information_slots": [],
        "produces_information_slots": ["backtest_performance_summary"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "selected_model_or_strategy"},
        "freshness_semantics": {"policy": "latest_saved_backtest"},
        "authority_level": "internal_backtest_store",
    },
    (W02, "query_selected_strategy"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["selected_strategy_state"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "current_user"},
        "freshness_semantics": {"policy": "current_selected_strategy"},
        "authority_level": "internal_strategy_store",
    },
    (W02, "query_portfolio_state"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["current_portfolio_state", "portfolio_positions", "authoritative_holding_entities"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "all_active_positions", "report_unresolved_positions": True},
        "freshness_semantics": {"policy": "requested_as_of_time_or_latest_snapshot"},
        "authority_level": "portfolio_repository",
    },
    (W02, "load_portfolio_snapshot"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["current_portfolio_state", "portfolio_snapshot_ref", "authoritative_holding_entities"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "portfolio_snapshot"},
        "freshness_semantics": {"policy": "requested_as_of_time_or_latest_snapshot"},
        "authority_level": "portfolio_repository",
    },
    (W02, "analyze_portfolio"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["current_portfolio_state", "portfolio_structure_facts", "authoritative_holding_entities"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "all_active_positions", "risk_conclusions_excluded": True},
        "freshness_semantics": {"policy": "requested_as_of_time_or_latest_snapshot"},
        "authority_level": "portfolio_repository",
    },
    (W02, "analyze_portfolio_fit"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["current_portfolio_state", "portfolio_fit_state_baseline"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "all_active_positions", "fit_conclusion_excluded": True},
        "freshness_semantics": {"policy": "requested_as_of_time_or_latest_snapshot"},
        "authority_level": "portfolio_repository",
    },
    (W02, "compare_portfolios"): {
        "consumes_information_slots": ["user_identity", "portfolio_references"],
        "produces_information_slots": ["portfolio_comparison_state_facts"],
        "required_context_slots": ["user_identity", "portfolio_references"],
        "coverage_semantics": {"scope": "all_resolved_portfolios", "risk_comparison_excluded": True},
        "freshness_semantics": {"policy": "aligned_snapshot_times_when_available"},
        "authority_level": "portfolio_repository",
    },
    (W02, "query_account_state"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["account_financial_state"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "current_user_account_summary"},
        "freshness_semantics": {"policy": "current_account_state"},
        "authority_level": "account_repository",
    },
    (W02, "query_user_profile"): {
        "consumes_information_slots": ["user_identity"],
        "produces_information_slots": ["user_profile_constraints"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "current_user_profile"},
        "freshness_semantics": {"policy": "latest_confirmed_profile"},
        "authority_level": "user_profile_repository",
    },
    (W02, "resolve_context"): {
        "consumes_information_slots": ["user_identity", "partial_portfolio_context"],
        "produces_information_slots": ["current_portfolio_state", "resolved_portfolio_context"],
        "required_context_slots": ["user_identity"],
        "coverage_semantics": {"scope": "missing_portfolio_context", "may_return_need_context": True},
        "freshness_semantics": {"policy": "preserve_requested_as_of_time"},
        "authority_level": "portfolio_repository",
    },
    (W03, "analyze_graph_impact"): {
        "consumes_information_slots": ["entity_evidence_analysis", "current_portfolio_state"],
        "produces_information_slots": ["portfolio_impact_analysis", "impact_relation_paths"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "evidence_to_portfolio_relations", "claims_require_graph_paths": True},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "financial_graph_derived_analysis",
    },
    (W03, "map_evidence_to_holdings"): {
        "consumes_information_slots": ["entity_external_evidence", "current_portfolio_state"],
        "produces_information_slots": ["holding_evidence_mapping", "portfolio_impact_analysis"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "current_holdings", "report_unmapped_evidence": True},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "financial_graph_derived_analysis",
    },
    (W03, "trace_financial_relation"): {
        "consumes_information_slots": ["authoritative_financial_entities"],
        "produces_information_slots": ["financial_relation_paths", "portfolio_impact_analysis"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "resolved_graph_paths"},
        "freshness_semantics": {"policy": "graph_current_state"},
        "authority_level": "financial_graph",
    },
    (W03, "resolve_context"): {
        "consumes_information_slots": ["partial_impact_context"],
        "produces_information_slots": ["resolved_impact_context", "portfolio_impact_analysis"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "missing_impact_context", "may_return_need_context": True},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "financial_graph_derived_analysis",
    },
    (W04, "analyze_risk"): {
        "consumes_information_slots": ["current_portfolio_state"],
        "produces_information_slots": ["portfolio_risk_assessment", "portfolio_risk_constraints"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_portfolio_state", "risk_claims_grounded_only": True},
        "freshness_semantics": {"policy": "inherit_portfolio_as_of_time"},
        "authority_level": "specialist_risk_analysis",
    },
    (W04, "compare_risk"): {
        "consumes_information_slots": ["portfolio_comparison_state_facts"],
        "produces_information_slots": ["comparative_portfolio_risk", "portfolio_risk_constraints"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "all_provided_portfolios"},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "specialist_risk_analysis",
    },
    (W04, "review_risk_constraints"): {
        "consumes_information_slots": ["current_portfolio_state", "user_profile_constraints"],
        "produces_information_slots": ["portfolio_risk_constraints", "constraint_review_result"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_state_and_constraints"},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "specialist_risk_analysis",
    },
    (W04, "resolve_context"): {
        "consumes_information_slots": ["partial_risk_context"],
        "produces_information_slots": ["resolved_risk_context", "portfolio_risk_assessment"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "missing_risk_context", "may_return_need_context": True},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "specialist_risk_analysis",
    },
    (W05, "build_proposal"): {
        "consumes_information_slots": ["current_state_for_change", "optional_risk_constraints", "optional_supporting_analysis"],
        "produces_information_slots": ["reviewed_proposal", "proposal_approval_boundary"],
        "required_context_slots": ["explicit_change_intent"],
        "coverage_semantics": {"scope": "declared_change_scope", "proposal_only": True, "execution_performed": False},
        "freshness_semantics": {"policy": "use_current_upstream_state"},
        "authority_level": "proposal_boundary",
    },
    (W05, "review_strategy"): {
        "consumes_information_slots": ["selected_strategy_state", "explicit_change_intent", "optional_supporting_analysis"],
        "produces_information_slots": ["reviewed_proposal", "strategy_review_result"],
        "required_context_slots": ["explicit_change_intent"],
        "coverage_semantics": {"scope": "current_strategy", "proposal_only": True, "execution_performed": False},
        "freshness_semantics": {"policy": "use_current_selected_strategy"},
        "authority_level": "proposal_boundary",
    },
    (W05, "review_proposal"): {
        "consumes_information_slots": ["existing_reviewed_proposal", "optional_risk_constraints", "optional_supporting_analysis"],
        "produces_information_slots": ["reviewed_proposal", "proposal_review_result"],
        "required_context_slots": ["existing_reviewed_proposal"],
        "coverage_semantics": {"scope": "existing_proposal", "proposal_only": True, "execution_performed": False},
        "freshness_semantics": {"policy": "revalidate_against_current_upstream_state"},
        "authority_level": "proposal_boundary",
    },
    (W06, "write_report"): {
        "consumes_information_slots": ["specialist_worker_results"],
        "produces_information_slots": ["user_facing_report", "goal_completion_summary"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "all_goal_relevant_upstream_results", "no_new_business_claims": True},
        "freshness_semantics": {"policy": "preserve_upstream_dates"},
        "authority_level": "grounded_report_synthesis",
    },
    (W06, "summarize_results"): {
        "consumes_information_slots": ["existing_worker_results"],
        "produces_information_slots": ["user_facing_summary"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_results_only", "no_new_business_claims": True},
        "freshness_semantics": {"policy": "preserve_upstream_dates"},
        "authority_level": "grounded_report_synthesis",
    },
    (W07, "diagnose_system"): {
        "consumes_information_slots": ["diagnostic_target", "optional_error_context"],
        "produces_information_slots": ["system_diagnostic_result", "failure_classification"],
        "required_context_slots": ["diagnostic_target"],
        "coverage_semantics": {"scope": "declared_diagnostic_target"},
        "freshness_semantics": {"policy": "current_runtime_state"},
        "authority_level": "system_diagnostic",
    },
    (W07, "inspect_runtime"): {
        "consumes_information_slots": ["diagnostic_target", "optional_run_context"],
        "produces_information_slots": ["runtime_inspection_result", "failure_classification"],
        "required_context_slots": ["diagnostic_target"],
        "coverage_semantics": {"scope": "specified_run_or_runtime_component"},
        "freshness_semantics": {"policy": "current_or_persisted_run_state"},
        "authority_level": "system_diagnostic",
    },
    (W07, "resolve_context"): {
        "consumes_information_slots": ["partial_diagnostic_context"],
        "produces_information_slots": ["resolved_diagnostic_context", "system_diagnostic_result"],
        "required_context_slots": ["diagnostic_target"],
        "coverage_semantics": {"scope": "missing_diagnostic_context", "may_return_need_context": True},
        "freshness_semantics": {"policy": "current_or_persisted_run_state"},
        "authority_level": "system_diagnostic",
    },
}


def _apply_forward_semantics(worker_id: str, contract: WorkerTaskContract) -> WorkerTaskContract:
    """Attach explicit information-slot semantics to a task capability.

    The mapping is intentionally keyed by ``(worker_id, task_type)`` because
    several Workers expose a ``resolve_context`` task with different business
    meanings.  Missing entries are rejected during directory construction so
    new capabilities cannot silently bypass forward-planning metadata.
    """

    key = (str(worker_id or "").upper(), str(contract.task_type or ""))
    semantics = _FORWARD_TASK_SEMANTICS.get(key)
    if semantics is None:
        raise ValueError(f"missing_forward_task_semantics:{key[0]}:{key[1]}")
    return replace(contract, **semantics)


def _task_ids(*, min_items: int = 1) -> dict[str, Any]:
    return array_schema(string_schema(min_length=1), min_items=min_items, max_items=8)


def _ref_ids(*, min_items: int = 1) -> dict[str, Any]:
    return array_schema(string_schema(min_length=1), min_items=min_items, max_items=30)


def _free_object() -> dict[str, Any]:
    return object_schema({}, additional_properties=True)


def _entity_research_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "EntityResearchResult",
        data_schema=object_schema(
            {
                "entity_refs": array_schema(_free_object()),
                "research_question": {"type": "string"},
                "results": array_schema(_free_object()),
                "evidence_refs": array_schema(_free_object()),
                "conclusion": {"type": "string"},
            },
            required=["entity_refs", "research_question", "results"],
            additional_properties=True,
        ),
    )


def _portfolio_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "PortfolioAnalysisResult",
        data_schema=object_schema(
            {
                "portfolio_ref": _free_object(),
                "holding_refs": array_schema(_free_object()),
                "entity_catalog": array_schema(_free_object()),
                "display_positions": array_schema(_free_object()),
                "portfolio_summary": _free_object(),
                "unresolved_positions": array_schema(_free_object()),
            },
            required=[
                "portfolio_ref",
                "holding_refs",
                "entity_catalog",
                "display_positions",
                "portfolio_summary",
            ],
            additional_properties=True,
        ),
    )


def _impact_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "ImpactAnalysisResult",
        data_schema=object_schema(
            {
                "source_task_ids": _task_ids(),
                "target_task_ids": _task_ids(),
                "impact_paths": array_schema(_free_object()),
                "impact_summary": _free_object(),
            },
            required=[
                "source_task_ids",
                "target_task_ids",
                "impact_paths",
                "impact_summary",
            ],
            additional_properties=True,
        ),
    )


def _risk_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "PortfolioRiskResult",
        data_schema=object_schema(
            {
                "portfolio_task_ids": _task_ids(),
                "risk_analysis": _free_object(),
                "records": array_schema(_free_object()),
            },
            required=["portfolio_task_ids", "risk_analysis"],
            additional_properties=True,
        ),
    )


def _reviewed_proposal_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "ReviewedProposal",
        data_schema=object_schema(
            {
                "proposal_id": {"type": "string"},
                "plan_id": {"type": "string"},
                "proposal": _free_object(),
                "requires_approval": {"type": "boolean"},
                "execution_allowed": {"type": "boolean"},
            },
            required=["requires_approval", "execution_allowed"],
            additional_properties=True,
        ),
    )


def _final_report_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "FinalReport",
        data_schema=object_schema(
            {
                "title": {"type": "string"},
                "language": string_schema(enum=["zh", "en"]),
                "source_task_ids": _task_ids(),
                "content": string_schema(min_length=1),
                "limitations": array_schema({"type": "string"}),
            },
            required=["language", "source_task_ids", "content"],
            additional_properties=True,
        ),
    )


def _diagnostic_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "DiagnosticResult",
        data_schema=object_schema(
            {
                "diagnostic_target": {"type": "string"},
                "checked_components": array_schema({"type": "string"}),
                "findings": array_schema(_free_object()),
                "root_cause": {"type": "string"},
            },
            required=["diagnostic_target", "checked_components", "findings"],
            additional_properties=True,
        ),
    )


class AgentDirectory:
    """MainAgent-facing Worker contracts plus private runtime metadata.

    MainAgent receives only the structured public Worker cards. Private Tool
    identifiers and Worker implementation prompts remain available to the
    assigned Worker runtime and are never exposed through ``safe_catalog``.
    """

    def __init__(self) -> None:
        cards = [
            AgentCapabilityCard(
                worker_id=W01,
                agent_id=EVIDENCE_RETRIEVER,
                role=EVIDENCE_RETRIEVER,
                description=(
                    "负责围绕一个或多个已经解析并锁定的金融实体，检索、整理、分析和比较外部证据。"
                    "W01 处理新闻、公告、研报等证据层信息，输出带来源引用的 EntityResearchResult；"
                    "它不读取用户账户或持仓，不评估组合风险，也不生成调仓或状态变更方案。"
                ),
                responsibility=(
                    "把用户的实体研究问题转换为可追踪的证据研究结果，明确证据时间、来源、"
                    "覆盖范围和不确定性，并保持金融实体 GraphRef 在整个研究过程中一致。"
                ),
                accepted_task_types=[
                    "retrieve_evidence",
                    "analyze_entity_evidence",
                    "compare_entity_evidence",
                    "ingest_evidence",
                    "resolve_context",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="retrieve_evidence",
                        description=(
                            "围绕已确认金融实体检索与用户问题直接相关的外部证据，"
                            "适用于用户要求查看新闻、公告、研报、事件或证据来源的场景。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "research_question": string_schema(min_length=1),
                                "time_range": _free_object(),
                            },
                            required=["focus_ref_ids", "research_question"],
                        ),
                        output_schema=_entity_research_result_schema(),
                        output_type="EntityResearchResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "用户目标必须涉及已解析金融实体的外部证据、新闻、公告或研报。",
                            "只需要本系统内部模型、账户、持仓或策略事实时不得选择。",
                        ],
                        user_goal_examples=[
                            "查询这只股票最近有哪些重要公告",
                            "找出影响该公司的最新证据并给出来源",
                        ],
                        negative_goal_examples=[
                            "查看我的当前持仓",
                            "分析我的组合风险",
                        ],
                        completion_criteria=[
                            "返回与研究问题相关的结构化结果和 evidence_refs。",
                            "明确没有检索到证据或证据不足的情况，不得自行补造。",
                        ],
                        planning_notes=[
                            "只使用任务中由运行时绑定的权威 focus_ref_ids。",
                            "该任务只产出证据研究结果，不直接形成组合或策略结论。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_and_derived_evidence", "commits_state": False},
                        private_tool_ids=[
                            "graph.evidence.analyze_entities",
                            "graph.evidence.retrieve",
                        ],
                    ),
                    WorkerTaskContract(
                        task_type="analyze_entity_evidence",
                        description=(
                            "对已检索或可读取的实体证据进行归纳、冲突识别和结论提炼，"
                            "适用于用户询问某个事件、公告或新闻对实体本身意味着什么。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "research_question": string_schema(min_length=1),
                                "time_range": _free_object(),
                            },
                            required=["focus_ref_ids", "research_question"],
                        ),
                        output_schema=_entity_research_result_schema(),
                        output_type="EntityResearchResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "用户要求解释、归纳或判断实体证据本身时选择。",
                            "用户要求组合影响时应由其他 Worker 消费本任务输出，而不是由 W01直接判断组合。",
                        ],
                        user_goal_examples=[
                            "分析这些公告对公司的主要影响",
                            "总结该股票近期证据中的一致结论和冲突点",
                        ],
                        negative_goal_examples=[
                            "这些新闻会怎样影响我的持仓组合",
                            "给我生成调仓方案",
                        ],
                        completion_criteria=[
                            "结论可追溯到 evidence_refs。",
                            "区分事实、证据解释和不确定性。",
                        ],
                        planning_notes=[
                            "只分析实体层证据；组合映射应交给能够输出 ImpactAnalysisResult 的能力。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_and_derived_evidence", "commits_state": False},
                        private_tool_ids=[
                            "graph.evidence.analyze_entities",
                            "graph.evidence.retrieve",
                        ],
                    ),
                    WorkerTaskContract(
                        task_type="compare_entity_evidence",
                        description=(
                            "比较两个或多个已解析金融实体的证据、事件和研究结论，"
                            "输出可追踪的差异与共同点，不延伸到用户组合风险或交易建议。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(min_items=2),
                                "research_question": string_schema(min_length=1),
                                "time_range": _free_object(),
                                "comparison_mode": {"type": "boolean", "default": True},
                            },
                            required=["focus_ref_ids", "research_question"],
                        ),
                        default_args={"comparison_mode": True},
                        output_schema=_entity_research_result_schema(),
                        output_type="EntityResearchResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "至少存在两个已解析实体，并且用户明确要求比较证据或事件。",
                        ],
                        user_goal_examples=[
                            "比较贵州茅台和五粮液最近公告的差异",
                            "对比两只股票近期新闻证据",
                        ],
                        negative_goal_examples=[
                            "比较我两个组合的风险",
                        ],
                        completion_criteria=[
                            "分别保留各实体证据来源，并给出共同点与差异。",
                        ],
                        planning_notes=[
                            "比较对象来自权威 GraphRef，不能由 MainAgent自行拼写代码。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_and_derived_evidence", "commits_state": False},
                        private_tool_ids=[
                            "graph.evidence.analyze_entities",
                            "graph.evidence.retrieve",
                        ],
                    ),
                    WorkerTaskContract(
                        task_type="ingest_evidence",
                        description=(
                            "把允许进入证据层的外部材料解析并写入派生证据图，"
                            "用于用户明确要求更新、导入或刷新证据数据的场景。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "research_question": string_schema(min_length=1),
                                "time_range": _free_object(),
                            },
                            required=["focus_ref_ids", "research_question"],
                        ),
                        output_schema=_entity_research_result_schema(),
                        output_type="EntityResearchResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "只有用户目标明确要求导入、刷新或更新证据层时选择。",
                            "普通查询和分析优先选择 retrieve_evidence 或 analyze_entity_evidence。",
                        ],
                        user_goal_examples=[
                            "刷新这只股票最近五天的公告证据",
                        ],
                        negative_goal_examples=[
                            "只查看已有新闻",
                        ],
                        completion_criteria=[
                            "返回本次写入或刷新后的可追踪证据结果。",
                        ],
                        planning_notes=[
                            "只允许派生证据图写入，不允许修改账户、持仓或策略状态。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={
                            "kind": "derived_evidence_graph_upsert_only",
                            "commits_business_state": False,
                        },
                        private_tool_ids=[
                            "graph.evidence.analyze_entities",
                            "graph.evidence.retrieve",
                        ],
                    ),
                    WorkerTaskContract(
                        task_type="resolve_context",
                        description=(
                            "围绕已解析金融实体补齐研究问题所需的证据上下文；"
                            "无法补齐时返回明确的缺失上下文，而不是猜测。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "research_question": string_schema(min_length=1),
                                "time_range": _free_object(),
                            },
                            required=["focus_ref_ids", "research_question"],
                        ),
                        output_schema=_entity_research_result_schema(),
                        output_type="EntityResearchResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "研究目标已经明确，但完成研究仍缺少证据上下文时选择。",
                        ],
                        user_goal_examples=[
                            "补齐上一轮股票研究缺少的公告上下文",
                        ],
                        negative_goal_examples=[
                            "补齐用户账户ID",
                        ],
                        completion_criteria=[
                            "返回可用研究结果或明确的 need_context。",
                        ],
                        planning_notes=[
                            "该能力只处理证据研究上下文，不处理用户参数和组合状态。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_and_derived_evidence", "commits_state": False},
                        private_tool_ids=[
                            "graph.evidence.analyze_entities",
                            "graph.evidence.retrieve",
                        ],
                    ),
                ],
                input_schema=object_schema(
                    {
                        "focus_ref_ids": _ref_ids(),
                        "research_question": string_schema(min_length=1),
                        "time_range": _free_object(),
                        "comparison_mode": {"type": "boolean"},
                    },
                    required=["focus_ref_ids", "research_question"],
                ),
                authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                output_schema=_entity_research_result_schema(),
                output_types=["EntityResearchResult"],
                selection_requirements=[
                    "只处理已确认金融实体的外部证据研究。",
                    "MainAgent 应依据具体 task_contract 区分检索、分析、比较、导入和上下文补齐。",
                ],
                non_responsibilities=[
                    "读取或解释用户组合状态",
                    "评估用户组合层面的风险",
                    "生成状态调整 Proposal",
                    "执行任何业务状态变更",
                ],
                side_effects=["derived_evidence_graph_upsert_only"],
                private_tool_ids=[
                    "graph.evidence.analyze_entities",
                    "graph.evidence.retrieve",
                ],
                private_worker_prompt=(
                    "你负责金融实体证据研究。严格依据 task_type、权威 GraphRef 和研究问题工作；"
                    "不得读取用户组合、生成 Proposal 或执行状态变更。"
                    "最终必须返回 EntityResearchResult WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W02,
                agent_id=PORTFOLIO_ANALYST,
                role="INTERNAL_SYSTEM_RETRIEVER",
                description=(
                    "负责读取并标准化本系统已经存在的权威结构化事实，包括证券预测、全市场排名、"
                    "模型指标、回测摘要、当前策略、用户画像、账户资金和组合持仓。"
                    "W02 是内部事实查询 Worker，不检索外部新闻，不形成风险结论，不生成买卖建议或 Proposal。"
                ),
                responsibility=(
                    "根据每个 task_type 调用对应只读内部能力，把结果转换为稳定强类型 WorkerResult，"
                    "并维护用户、证券、账户和组合实体在跨 Worker 传递中的一致性。"
                ),
                accepted_task_types=[
                    "query_stock_prediction",
                    "query_latest_ranking",
                    "query_model_metrics",
                    "query_backtest_summary",
                    "query_selected_strategy",
                    "query_portfolio_state",
                    "load_portfolio_snapshot",
                    "analyze_portfolio",
                    "analyze_portfolio_fit",
                    "compare_portfolios",
                    "query_account_state",
                    "query_user_profile",
                    "resolve_context",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="query_stock_prediction",
                        description=(
                            "查询一个或多个已解析证券在指定或最新模型预测中的评分、排名和 TopK 状态。"
                            "用于证券级模型信号查询，不用于获取全市场候选列表或组合级调仓依据。"
                        ),
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "top_k": {
                                    "type": "integer",
                                    "default": 10,
                                    "description": "判断证券 TopK 状态时使用的范围，默认10。",
                                },
                                "model_name": {
                                    "type": "string",
                                    "description": "仅在用户明确指定模型时填写，否则省略。",
                                },
                                "trade_date": {
                                    "type": "string",
                                    "description": "仅在用户明确指定日期时填写，否则查询最新可用日期。",
                                },
                            },
                            required=["focus_ref_ids"],
                        ),
                        default_args={"top_k": 10},
                        output_schema=worker_result_schema(
                            "ModelPredictionResult",
                            data_schema=object_schema(
                                {
                                    "security_ref": _free_object(),
                                    "found": {"type": "boolean"},
                                    "record": _free_object(),
                                    "data_date": {"type": "string"},
                                    "rank": {"type": ["integer", "null"]},
                                    "is_topk": {"type": "boolean"},
                                    "total_count": {"type": "integer"},
                                    "source_id": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                required=[
                                    "security_ref", "found", "record", "data_date",
                                    "rank", "is_topk", "total_count", "source_id", "reason",
                                ],
                                additional_properties=True,
                            ),
                        ),
                        output_type="ModelPredictionResult",
                        authoritative_arg_bindings={"focus_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "用户明确询问某只已解析证券的模型预测、评分、排名或 TopK 状态时选择。",
                            "用户需要全市场排名候选时应选择 query_latest_ranking。",
                        ],
                        user_goal_examples=[
                            "600519 当前模型评分和排名是多少",
                            "这只股票是否进入最新 Top10",
                        ],
                        negative_goal_examples=[
                            "列出最新模型前50名",
                            "根据我的整个持仓生成调仓方案",
                        ],
                        completion_criteria=[
                            "每个证券使用权威 GraphRef，并返回 found、rank、is_topk 和数据日期。",
                            "不存在记录时返回业务结果为空，不得伪造预测。",
                        ],
                        planning_notes=[
                            "focus_ref_ids 由运行时绑定；不要把组合快照 GraphRef 当作证券 GraphRef。",
                            "该任务只产出证券级 ModelPredictionResult。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.prediction.get_stock"],
                    ),
                    WorkerTaskContract(
                        task_type="query_latest_ranking",
                        description=(
                            "查询当前激活模型或用户指定模型的最新全市场预测排名，返回候选证券及其评分。"
                            "适用于排名列表、候选池和需要横截面模型信号的上游分析。"
                        ),
                        input_schema=object_schema(
                            {
                                "top_k": {
                                    "type": "integer",
                                    "default": 10,
                                    "description": "返回的排名数量，默认10；应根据用户目标合理设置。",
                                },
                                "model_name": {
                                    "type": "string",
                                    "description": "仅在用户明确指定模型时填写，否则省略。",
                                },
                            },
                            required=[],
                        ),
                        default_args={"top_k": 10},
                        output_schema=worker_result_schema("RankingResult", data_schema=_free_object()),
                        output_type="RankingResult",
                        selection_requirements=[
                            "用户要求最新排名、TopK候选或后续能力需要全市场横截面模型信号时选择。",
                            "只查询单个证券模型结果时不要选择。",
                        ],
                        user_goal_examples=[
                            "查看最新模型Top20",
                            "获取可用于组合分析的最新排名信号",
                        ],
                        negative_goal_examples=[
                            "查询贵州茅台当前排名",
                        ],
                        completion_criteria=[
                            "返回明确的数据日期、模型来源和不超过 top_k 的结构化记录。",
                        ],
                        planning_notes=[
                            "top_k 应由用户目标决定，不得在程序中为某个业务场景写死。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.ranking.get_latest"],
                    ),
                    WorkerTaskContract(
                        task_type="query_model_metrics",
                        description=(
                            "查询当前激活模型或指定模型的评估指标，用于解释模型质量、稳定性和适用范围。"
                        ),
                        input_schema=object_schema(
                            {"model_name": {"type": "string"}}, required=[]
                        ),
                        output_schema=worker_result_schema("ModelMetricsResult", data_schema=_free_object()),
                        output_type="ModelMetricsResult",
                        selection_requirements=[
                            "用户询问模型IC、RIC、稳定性、评估指标或模型表现时选择。",
                        ],
                        user_goal_examples=["当前模型的IC和ICIR是多少"],
                        negative_goal_examples=["这只股票今天的预测分数是多少"],
                        completion_criteria=["返回模型标识、指标值及可用数据范围。"],
                        planning_notes=["不要把模型指标当作单只证券预测。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.model.get_metrics"],
                    ),
                    WorkerTaskContract(
                        task_type="query_backtest_summary",
                        description=(
                            "查询模型或策略已经保存的历史回测摘要，用于评估历史收益、回撤和交易特征。"
                        ),
                        input_schema=object_schema(
                            {
                                "model_name": {"type": "string"},
                                "top_k": {"type": "integer"},
                                "holding_period": {"type": "integer"},
                            },
                            required=[],
                        ),
                        output_schema=worker_result_schema("BacktestSummaryResult", data_schema=_free_object()),
                        output_type="BacktestSummaryResult",
                        selection_requirements=[
                            "用户明确询问历史回测、累计收益、回撤、换手或策略历史表现时选择。",
                        ],
                        user_goal_examples=["查看当前策略的回测摘要"],
                        negative_goal_examples=["查看当前模拟盘账户收益"],
                        completion_criteria=["返回回测配置、时间范围和指标摘要。"],
                        planning_notes=["历史回测结果不等同于当前账户状态。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.backtest.get_summary"],
                    ),
                    WorkerTaskContract(
                        task_type="query_selected_strategy",
                        description=(
                            "查询用户当前已选定或系统当前激活的策略配置，返回权威策略事实。"
                        ),
                        input_schema=object_schema({}, required=[]),
                        output_schema=worker_result_schema("SelectedStrategyResult", data_schema=_free_object()),
                        output_type="SelectedStrategyResult",
                        selection_requirements=[
                            "用户询问当前策略配置，或后续 Proposal 需要以当前策略作为状态基线时选择。",
                        ],
                        user_goal_examples=["我现在使用的是什么策略"],
                        negative_goal_examples=["帮我修改策略"],
                        completion_criteria=["返回当前选定策略及其关键配置。"],
                        planning_notes=["只查询策略，不修改策略。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.strategy.get_selected"],
                    ),
                    *[
                        WorkerTaskContract(
                            task_type=task_type,
                            description=spec["description"],
                            input_schema=object_schema(
                                {
                                    "user_id": string_schema(min_length=1),
                                    "as_of_time": {"type": "string"},
                                    "portfolio_ref_ids": _ref_ids(min_items=0),
                                },
                                required=["user_id"],
                            ),
                            output_schema=_portfolio_result_schema(),
                            output_type="PortfolioAnalysisResult",
                            authoritative_arg_bindings={
                                "user_id": "user_id",
                                "as_of_time": "as_of_time",
                            },
                            selection_requirements=spec["selection_requirements"],
                            user_goal_examples=spec["user_goal_examples"],
                            negative_goal_examples=spec["negative_goal_examples"],
                            completion_criteria=[
                                "返回权威 portfolio_ref、holding_refs、entity_catalog、display_positions 和 portfolio_summary。",
                                "证券代码和名称必须来自统一实体链路。",
                            ],
                            planning_notes=spec["planning_notes"],
                            allowed_request_modes=["analysis", "proposal"],
                            side_effect_policy={
                                "kind": "read_and_derived_portfolio_snapshot",
                                "commits_business_state": False,
                            },
                            private_tool_ids=["internal.portfolio.get_state"],
                        )
                        for task_type, spec in {
                            "query_portfolio_state": {
                                "description": "查询当前用户账户对应的最新权威组合和持仓状态，适用于查看当前持仓、仓位和组合市值。",
                                "selection_requirements": ["用户明确需要当前组合或持仓事实时选择。"],
                                "user_goal_examples": ["查看我当前的模拟盘持仓"],
                                "negative_goal_examples": ["分析一只不在持仓中的股票"],
                                "planning_notes": ["只返回状态事实，不形成风险或调整建议。"],
                            },
                            "load_portfolio_snapshot": {
                                "description": "按当前运行上下文或指定时间读取权威组合快照，供其他专业 Worker 使用。",
                                "selection_requirements": ["后续能力需要一个明确的组合状态基线时选择。"],
                                "user_goal_examples": ["读取用于后续分析的当前组合快照"],
                                "negative_goal_examples": ["只查询账户现金"],
                                "planning_notes": ["该任务是状态基线生产者，不承担分析结论。"],
                            },
                            "analyze_portfolio": {
                                "description": "读取并结构化展示当前组合构成、仓位和持仓事实；名称保留为历史兼容，但不生成风险结论。",
                                "selection_requirements": ["用户需要组合结构事实，而不是风险判断时选择。"],
                                "user_goal_examples": ["分析一下我当前组合都持有哪些股票"],
                                "negative_goal_examples": ["我的组合风险高不高"],
                                "planning_notes": ["需要风险结论时应由能输出 PortfolioRiskResult 的能力消费本结果。"],
                            },
                            "analyze_portfolio_fit": {
                                "description": "读取组合事实作为适配性分析的状态输入；W02本身不判断适配性，结果仍是 PortfolioAnalysisResult。",
                                "selection_requirements": ["后续风险或策略能力需要组合适配状态基线时选择。"],
                                "user_goal_examples": ["读取我的持仓用于风险画像适配分析"],
                                "negative_goal_examples": ["直接判断我的组合是否适合我"],
                                "planning_notes": ["适配结论必须由专业风险或策略能力形成。"],
                            },
                            "compare_portfolios": {
                                "description": "读取用于组合比较的权威组合快照；W02只提供事实，不自行给出风险优劣结论。",
                                "selection_requirements": ["用户目标需要比较组合状态且上下文中存在可解析组合引用时选择。"],
                                "user_goal_examples": ["读取两个组合的持仓用于比较"],
                                "negative_goal_examples": ["比较两只股票的新闻"],
                                "planning_notes": ["比较结论由消费这些状态结果的后续能力负责。"],
                            },
                            "resolve_context": {
                                "description": "补齐与当前用户组合相关的权威状态上下文；无法找到时返回上下文缺失。",
                                "selection_requirements": ["后续任务明确需要组合状态但当前上下文不足时选择。"],
                                "user_goal_examples": ["恢复上一轮分析所需的组合上下文"],
                                "negative_goal_examples": ["补齐某只股票的新闻证据"],
                                "planning_notes": ["只处理组合状态上下文，不替用户猜测缺失参数。"],
                            },
                        }.items()
                    ],
                    WorkerTaskContract(
                        task_type="query_account_state",
                        description=(
                            "查询当前用户账户资金摘要，包括现金、总资产和系统已提供的账户指标；"
                            "不读取持仓明细，不生成风险或策略结论。"
                        ),
                        input_schema=object_schema(
                            {"user_id": string_schema(min_length=1)}, required=["user_id"]
                        ),
                        output_schema=worker_result_schema("AccountStateResult", data_schema=_free_object()),
                        output_type="AccountStateResult",
                        authoritative_arg_bindings={"user_id": "user_id"},
                        selection_requirements=["用户需要账户资金、现金或总资产事实时选择。"],
                        user_goal_examples=["查看我当前模拟盘账户资金"],
                        negative_goal_examples=["查看每只持仓的成本价"],
                        completion_criteria=["返回当前账户权威资金摘要和数据时间。"],
                        planning_notes=["账户状态和组合持仓是两个不同输出，需要时应分别规划。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.account.get_state"],
                    ),
                    WorkerTaskContract(
                        task_type="query_user_profile",
                        description=(
                            "查询当前用户的权威风险画像、投资偏好和系统已保存约束，"
                            "供风险或 Proposal 能力使用；W02不自行判断适配性。"
                        ),
                        input_schema=object_schema(
                            {"user_id": string_schema(min_length=1)}, required=["user_id"]
                        ),
                        output_schema=worker_result_schema("UserProfileResult", data_schema=_free_object()),
                        output_type="UserProfileResult",
                        authoritative_arg_bindings={"user_id": "user_id"},
                        selection_requirements=[
                            "用户询问风险画像，或后续能力需要用户约束和偏好时选择。",
                        ],
                        user_goal_examples=["查看我的风险画像", "读取用户偏好用于方案约束"],
                        negative_goal_examples=["直接给出调仓动作"],
                        completion_criteria=["返回当前用户画像及其来源和更新时间。"],
                        planning_notes=["用户画像是事实输入，不是风险或策略结论。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.user_profile.get"],
                    ),
                ],
                input_schema=object_schema({}, required=[], additional_properties=True),
                output_schema=_portfolio_result_schema(),
                output_types=[
                    "ModelPredictionResult", "RankingResult", "ModelMetricsResult",
                    "BacktestSummaryResult", "SelectedStrategyResult",
                    "PortfolioAnalysisResult", "AccountStateResult", "UserProfileResult",
                ],
                selection_requirements=[
                    "只用于查询本系统内部权威结构化事实。",
                    "MainAgent 必须根据具体 task_contract 选择输出类型，不得只凭 W02 名称猜测。",
                ],
                non_responsibilities=[
                    "外部新闻、公告或研报检索",
                    "组合风险结论",
                    "新闻影响判断",
                    "买卖建议",
                    "生成或执行调整方案",
                    "修改任何业务状态",
                ],
                side_effects=["derived_portfolio_graph_snapshot_only"],
                private_tool_ids=[
                    "internal.prediction.get_stock", "internal.ranking.get_latest",
                    "internal.model.get_metrics", "internal.backtest.get_summary",
                    "internal.strategy.get_selected", "internal.portfolio.get_state",
                    "internal.account.get_state", "internal.user_profile.get",
                ],
                private_worker_prompt=(
                    "你是本系统内部权威数据查询 Worker。严格根据 task_type 调用对应只读私有能力，"
                    "返回任务合同指定的强类型结果。不得检索外部新闻，不得生成风险结论、建议或写操作。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W03,
                agent_id=GRAPH_IMPACT_ANALYST,
                role=GRAPH_IMPACT_ANALYST,
                description=(
                    "负责把上游实体研究结果映射到上游组合或持仓状态，分析证据对象、金融实体和持仓之间的"
                    "可追踪关系路径。W03 只解释已有研究结果怎样关联当前组合，不自行检索证据、读取组合或生成调仓方案。"
                ),
                responsibility=(
                    "基于明确的 source_analysis 与 target_state，形成 ImpactAnalysisResult，"
                    "保留关系路径、涉及持仓、影响方向和证据限制。"
                ),
                accepted_task_types=[
                    "analyze_graph_impact",
                    "map_evidence_to_holdings",
                    "trace_financial_relation",
                    "resolve_context",
                ],
                task_contracts=[
                    *[
                        WorkerTaskContract(
                            task_type=task_type,
                            description=spec["description"],
                            input_schema=object_schema(
                                {"analysis_question": string_schema(min_length=1)},
                                required=["analysis_question"],
                            ),
                            output_schema=_impact_result_schema(),
                            output_type="ImpactAnalysisResult",
                            upstream_input_bindings={
                                "source_analysis": {
                                    "description": (
                                        "已经由证据研究 Worker 形成的实体研究结果，"
                                        "用于提供影响分析的源事实与证据。"
                                    ),
                                    "accepted_output_types": ["EntityResearchResult"],
                                    "required": True,
                                    "min_items": 1,
                                    "max_items": 8,
                                },
                                "target_state": {
                                    "description": (
                                        "已经由内部状态 Worker 形成的当前组合或持仓结果，"
                                        "用于确定影响分析的目标对象。"
                                    ),
                                    "accepted_output_types": ["PortfolioAnalysisResult"],
                                    "required": True,
                                    "min_items": 1,
                                    "max_items": 8,
                                },
                            },
                            selection_requirements=spec["selection_requirements"],
                            user_goal_examples=spec["user_goal_examples"],
                            negative_goal_examples=spec["negative_goal_examples"],
                            completion_criteria=[
                                "输出 source_task_ids、target_task_ids、impact_paths 和 impact_summary。",
                                "每个影响结论能够回溯到上游实体研究和组合状态。",
                            ],
                            planning_notes=spec["planning_notes"],
                            allowed_request_modes=["analysis", "proposal"],
                            side_effect_policy={"kind": "derived_analysis_only", "commits_state": False},
                            required_upstream_output_groups=[
                                ["EntityResearchResult"],
                                ["PortfolioAnalysisResult"],
                            ],
                        )
                        for task_type, spec in {
                            "analyze_graph_impact": {
                                "description": "分析一个或多个实体研究结果对当前组合或持仓的可追踪影响路径和影响摘要。",
                                "selection_requirements": [
                                    "用户明确询问某个金融实体、新闻、公告或事件如何影响当前组合或持仓时选择。",
                                    "必须同时存在 EntityResearchResult 与 PortfolioAnalysisResult。",
                                ],
                                "user_goal_examples": [
                                    "这家公司最近的公告会影响我哪些持仓",
                                    "分析这个事件对当前组合的影响路径",
                                ],
                                "negative_goal_examples": [
                                    "分析这只股票本身的公告",
                                    "查看我当前持仓",
                                ],
                                "planning_notes": [
                                    "先由其他能力生产源证据和目标组合状态，再选择本任务。",
                                ],
                            },
                            "map_evidence_to_holdings": {
                                "description": "把上游实体证据逐项映射到当前持仓，识别哪些持仓被直接或间接关联。",
                                "selection_requirements": [
                                    "用户目标重点是证据与持仓对象的映射，而不是一般性影响解释时选择。",
                                ],
                                "user_goal_examples": ["把这些公告映射到我当前持仓"],
                                "negative_goal_examples": ["查询这些股票的最新排名"],
                                "planning_notes": [
                                    "只进行关系映射，不自行补充缺失证券或证据。",
                                ],
                            },
                            "trace_financial_relation": {
                                "description": "追踪源金融实体、关联关系和目标持仓之间的图路径，用于解释影响链路。",
                                "selection_requirements": [
                                    "用户明确要求关系链、传播路径或关联原因时选择。",
                                ],
                                "user_goal_examples": ["追踪这条新闻如何关联到我的持仓"],
                                "negative_goal_examples": ["生成具体减仓方案"],
                                "planning_notes": [
                                    "输出关系路径，不把关联关系直接转化为买卖建议。",
                                ],
                            },
                            "resolve_context": {
                                "description": "补齐影响分析所需的源研究结果和目标组合状态引用；无法补齐时返回上下文缺失。",
                                "selection_requirements": [
                                    "影响分析目标明确，但缺少可引用的源分析或目标状态上下文时选择。",
                                ],
                                "user_goal_examples": ["恢复上一轮影响分析需要的组合和证据上下文"],
                                "negative_goal_examples": ["补充用户风险偏好"],
                                "planning_notes": [
                                    "该任务不自行调用证据检索或组合查询能力。",
                                ],
                            },
                        }.items()
                    ],
                ],
                input_schema=object_schema(
                    {"analysis_question": string_schema(min_length=1)},
                    required=["analysis_question"],
                ),
                output_schema=_impact_result_schema(),
                output_types=["ImpactAnalysisResult"],
                required_upstream_output_groups=[
                    ["EntityResearchResult"],
                    ["PortfolioAnalysisResult"],
                ],
                upstream_input_bindings={
                    "source_analysis": {
                        "description": "实体研究或证据分析结果",
                        "accepted_output_types": ["EntityResearchResult"],
                        "required": True,
                        "min_items": 1,
                        "max_items": 8,
                    },
                    "target_state": {
                        "description": "当前组合状态分析结果",
                        "accepted_output_types": ["PortfolioAnalysisResult"],
                        "required": True,
                        "min_items": 1,
                        "max_items": 8,
                    },
                },
                selection_requirements=[
                    "只在用户目标需要把实体证据关联到当前组合或持仓时选择。",
                    "MainAgent 必须依据具体 task_contract 选择影响分析、持仓映射或关系追踪。",
                ],
                non_responsibilities=[
                    "自行检索缺失源证据",
                    "自行读取缺失组合状态",
                    "普通实体研究",
                    "生成状态调整 Proposal",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你负责分析上游实体研究结果到上游组合状态结果的可追踪关系。"
                    "不得自行补取源数据或目标状态，不得生成调整方案。"
                    "最终必须返回 ImpactAnalysisResult WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W04,
                agent_id=RISK_ANALYST,
                role=RISK_ANALYST,
                description=(
                    "负责基于上游组合状态、用户画像和可用分析结果，评估组合层面的集中度、回撤、"
                    "风险暴露、适配性和交易权限约束。W04 只形成 PortfolioRiskResult，"
                    "不检索原始证据、不决定具体买卖动作，也不生成或执行 Proposal。"
                ),
                responsibility=(
                    "把组合事实转换为可追踪的风险结论与约束，明确风险指标、触发原因、"
                    "适用范围和缺失数据，为报告或后续方案能力提供风险边界。"
                ),
                accepted_task_types=[
                    "analyze_risk",
                    "compare_risk",
                    "review_risk_constraints",
                    "resolve_context",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="analyze_risk",
                        description=(
                            "分析一个当前组合的集中度、回撤、暴露、用户适配性和权限风险，"
                            "适用于用户明确询问组合风险，或后续方案能力需要风险约束的场景。"
                        ),
                        input_schema=object_schema(
                            {"risk_question": string_schema(min_length=1)},
                            required=["risk_question"],
                        ),
                        output_schema=_risk_result_schema(),
                        output_type="PortfolioRiskResult",
                        upstream_input_bindings={
                            "portfolio_state": {
                                "description": "需要评估的权威当前组合状态。",
                                "accepted_output_types": ["PortfolioAnalysisResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            },
                            "user_constraints": {
                                "description": "可选的用户风险画像、账户或权限约束。",
                                "accepted_output_types": [
                                    "UserProfileResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                            "related_analysis": {
                                "description": "与风险问题直接相关的实体研究或影响分析。",
                                "accepted_output_types": [
                                    "EntityResearchResult",
                                    "ImpactAnalysisResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                        },
                        selection_requirements=[
                            "用户明确要求组合风险、集中度、回撤、风险暴露、适配性或权限分析时选择。",
                            "后续能力的输入合同明确需要 PortfolioRiskResult 时也可以选择。",
                            "普通证券研究或只查看组合状态时不得选择。",
                        ],
                        user_goal_examples=[
                            "分析我当前组合的集中度和回撤风险",
                            "评估当前持仓是否符合我的风险画像",
                        ],
                        negative_goal_examples=[
                            "查看我当前持仓",
                            "分析贵州茅台最近的公告",
                            "直接给出买卖数量",
                        ],
                        completion_criteria=[
                            "输出 portfolio_task_ids、risk_analysis 和可用风险记录。",
                            "所有结论只依赖上游组合和已提供约束。",
                        ],
                        planning_notes=[
                            "风险结论与具体调整动作分离；需要形成方案时由能输出 Proposal 的能力消费本结果。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_analysis_only", "commits_state": False},
                        required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                    ),
                    WorkerTaskContract(
                        task_type="compare_risk",
                        description=(
                            "比较两个或多个组合状态的风险差异，包括集中度、回撤、暴露和适配性差异。"
                        ),
                        input_schema=object_schema(
                            {"risk_question": string_schema(min_length=1)},
                            required=["risk_question"],
                        ),
                        output_schema=_risk_result_schema(),
                        output_type="PortfolioRiskResult",
                        upstream_input_bindings={
                            "portfolio_state": {
                                "description": "用于风险比较的两个或多个权威组合状态。",
                                "accepted_output_types": ["PortfolioAnalysisResult"],
                                "required": True,
                                "min_items": 2,
                                "max_items": 8,
                            },
                            "user_constraints": {
                                "description": "可选的统一用户画像或权限约束。",
                                "accepted_output_types": [
                                    "UserProfileResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                        },
                        selection_requirements=[
                            "至少存在两个可引用的 PortfolioAnalysisResult，且用户明确要求比较风险时选择。",
                        ],
                        user_goal_examples=["比较两个组合哪个风险更低"],
                        negative_goal_examples=["比较两只股票的模型评分"],
                        completion_criteria=["明确列出比较维度、差异和数据限制。"],
                        planning_notes=["比较对象必须来自上游组合结果，不能由文本猜测。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_analysis_only", "commits_state": False},
                        required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                    ),
                    WorkerTaskContract(
                        task_type="review_risk_constraints",
                        description=(
                            "审查已有策略、分析结果或待形成方案所受到的风险画像、账户权限和组合限制，"
                            "输出结构化风险约束，不生成具体 Proposal。"
                        ),
                        input_schema=object_schema(
                            {"risk_question": string_schema(min_length=1)},
                            required=["risk_question"],
                        ),
                        output_schema=_risk_result_schema(),
                        output_type="PortfolioRiskResult",
                        upstream_input_bindings={
                            "portfolio_state": {
                                "description": "需要审查风险约束的当前组合状态。",
                                "accepted_output_types": ["PortfolioAnalysisResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            },
                            "user_constraints": {
                                "description": "用户画像、账户或权限约束。",
                                "accepted_output_types": [
                                    "UserProfileResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                            "related_analysis": {
                                "description": "需要接受风险约束审查的上游分析结果。",
                                "accepted_output_types": [
                                    "EntityResearchResult",
                                    "ImpactAnalysisResult",
                                    "RankingResult",
                                    "SelectedStrategyResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                        },
                        selection_requirements=[
                            "用户要求检查某个策略或方案受到哪些风险和权限限制时选择。",
                            "只需要普通风险概览时优先选择 analyze_risk。",
                        ],
                        user_goal_examples=[
                            "审查这个调仓目标是否违反我的风险约束",
                            "检查当前策略的权限和仓位限制",
                        ],
                        negative_goal_examples=["直接生成待审批调仓方案"],
                        completion_criteria=["输出可以被后续方案能力直接引用的风险约束。"],
                        planning_notes=["该任务不批准、不执行，也不替代 Proposal 能力。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_analysis_only", "commits_state": False},
                        required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                    ),
                    WorkerTaskContract(
                        task_type="resolve_context",
                        description=(
                            "补齐风险分析所需的组合状态和用户约束引用；无法补齐时返回明确的上下文缺失。"
                        ),
                        input_schema=object_schema(
                            {"risk_question": string_schema(min_length=1)},
                            required=["risk_question"],
                        ),
                        output_schema=_risk_result_schema(),
                        output_type="PortfolioRiskResult",
                        upstream_input_bindings={
                            "portfolio_state": {
                                "description": "风险分析所需的组合状态。",
                                "accepted_output_types": ["PortfolioAnalysisResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            },
                            "user_constraints": {
                                "description": "可用的用户风险画像或账户约束。",
                                "accepted_output_types": [
                                    "UserProfileResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                        },
                        selection_requirements=[
                            "风险目标明确，但可用上游状态或约束不足时选择。",
                        ],
                        user_goal_examples=["恢复上一轮风险分析需要的组合上下文"],
                        negative_goal_examples=["补齐外部新闻证据"],
                        completion_criteria=["返回可用风险结果或明确 need_context。"],
                        planning_notes=["不得自行读取未声明的业务数据。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_analysis_only", "commits_state": False},
                        required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                    ),
                ],
                input_schema=object_schema(
                    {"risk_question": string_schema(min_length=1)},
                    required=["risk_question"],
                ),
                output_schema=_risk_result_schema(),
                output_types=["PortfolioRiskResult"],
                required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                upstream_input_bindings={
                    "portfolio_state": {
                        "description": "当前组合状态分析结果",
                        "accepted_output_types": ["PortfolioAnalysisResult"],
                        "required": True,
                        "min_items": 1,
                        "max_items": 8,
                    },
                    "related_analysis": {
                        "description": "与风险问题相关的实体或影响分析结果",
                        "accepted_output_types": [
                            "EntityResearchResult",
                            "ImpactAnalysisResult",
                        ],
                        "required": False,
                        "min_items": 0,
                        "max_items": 8,
                    },
                },
                selection_requirements=[
                    "只负责组合层风险、适配性和权限约束。",
                    "MainAgent 应根据具体 task_contract 区分单组合风险、风险比较、约束审查和上下文补齐。",
                ],
                non_responsibilities=[
                    "普通个体金融实体研究",
                    "读取原始市场证据",
                    "生成或执行状态调整",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你负责组合层风险评估，只使用任务声明的上游组合结果和约束。"
                    "不得进行普通实体研究，不得生成或执行调整方案。"
                    "最终必须返回 PortfolioRiskResult WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W05,
                agent_id=STRATEGY_GUARD,
                role=STRATEGY_GUARD,
                description=(
                    "负责把用户明确提出的状态变更目标，以及上游 Worker 提供的当前状态、风险约束、"
                    "模型信号、影响分析和用户约束，转换为结构化的待审批 Proposal；"
                    "也可以审查已有策略或 Proposal 是否具有充分依据并满足执行边界。"
                    "W05 只生成或审查 ReviewedProposal，不批准、不执行、不修改账户、持仓或策略。"
                ),
                responsibility=(
                    "管理分析结果进入状态变更流程的边界。区分新建预案、策略审查和已有 Proposal 审查，"
                    "检查事实依据、风险约束、权限限制和参数完整性，并始终保持 requires_approval=True、"
                    "execution_allowed=False，直到后续审批与重新校验完成。"
                ),
                accepted_task_types=[
                    "review_strategy",
                    "build_proposal",
                    "review_proposal",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="build_proposal",
                        description=(
                            "当用户明确要求形成一个具体但尚未执行的状态调整方案时选择。"
                            "该任务把权威当前状态、风险约束和支持分析转成待审批 ReviewedProposal，"
                            "可以描述拟调整对象、方向、目标参数和依据，但不能表示已经执行。"
                        ),
                        input_schema=object_schema(
                            {
                                "change_intent": string_schema(min_length=1),
                                "change_scope": string_schema(
                                    enum=[
                                        "portfolio_adjustment",
                                        "strategy_adjustment",
                                        "generic_state_change",
                                    ]
                                ),
                                "proposal_constraints": array_schema(
                                    string_schema(min_length=1)
                                ),
                            },
                            required=["change_intent", "change_scope"],
                        ),
                        output_schema=_reviewed_proposal_result_schema(),
                        output_type="ReviewedProposal",
                        upstream_input_bindings={
                            "current_state": {
                                "description": (
                                    "Proposal 所针对的权威当前状态。组合调整通常引用 PortfolioAnalysisResult；"
                                    "策略调整通常引用 SelectedStrategyResult。"
                                ),
                                "accepted_output_types": [
                                    "PortfolioAnalysisResult",
                                    "SelectedStrategyResult",
                                    "AccountStateResult",
                                ],
                                "required": True,
                                "min_items": 1,
                                "max_items": 4,
                            },
                            "risk_constraints": {
                                "description": (
                                    "决定方案边界的组合风险、用户适配性和权限约束。"
                                    "当变更会影响组合风险时应引用 PortfolioRiskResult。"
                                ),
                                "accepted_output_types": ["PortfolioRiskResult"],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                            "supporting_analysis": {
                                "description": (
                                    "支持调整方向和参数的模型信号、实体研究、影响分析、用户画像、"
                                    "回测摘要或其他系统权威事实。"
                                ),
                                "accepted_output_types": [
                                    "RankingResult",
                                    "ModelPredictionResult",
                                    "EntityResearchResult",
                                    "ImpactAnalysisResult",
                                    "UserProfileResult",
                                    "AccountStateResult",
                                    "BacktestSummaryResult",
                                    "ModelMetricsResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                        },
                        selection_requirements=[
                            "用户必须明确要求形成具体状态调整方案、调仓方案、目标配置或待审批预案。",
                            "用户只要求查看、解释、比较、研究或风险分析时不得选择。",
                            "用户要求立即执行时，本任务仍只能生成待审批 Proposal，后续执行必须经过独立审批链路。",
                            "MainAgent 应依据用户目标和本合同自行判断需要哪些 current_state、risk_constraints 和 supporting_analysis。",
                        ],
                        user_goal_examples=[
                            "你认为我的持仓应该怎么调整",
                            "根据当前风险和模型信号生成一份调仓预案",
                            "把这次分析结果转成待审批的目标仓位方案",
                        ],
                        negative_goal_examples=[
                            "查看当前持仓",
                            "分析我的组合风险",
                            "为什么这只股票排名下降",
                            "执行刚才的调仓方案",
                        ],
                        completion_criteria=[
                            "返回 ReviewedProposal，并包含 proposal、requires_approval 和 execution_allowed。",
                            "Proposal 中的对象、风险事实和模型信号均能回溯到声明的上游结果。",
                            "execution_allowed 必须为 False，且不得声称任何状态已经改变。",
                        ],
                        planning_notes=[
                            "先根据用户目标确定 change_scope，再从能力卡中寻找足够的权威上游结果。",
                            "不要预设固定 Worker 链路；只引用本次方案实际需要的上游输出。",
                            "缺少关键状态、约束或参数时，应由 W05 返回 need_context，而不是由 MainAgent猜测。",
                        ],
                        allowed_request_modes=["proposal"],
                        side_effect_policy={
                            "kind": "proposal_only",
                            "requires_approval": True,
                            "execution_allowed": False,
                            "commits_state": False,
                        },
                    ),
                    WorkerTaskContract(
                        task_type="review_strategy",
                        description=(
                            "审查当前策略或策略变更意图是否与用户目标、风险画像、回测事实和系统约束一致。"
                            "该任务可以形成经过审查的策略变更 Proposal，但不直接修改当前策略。"
                        ),
                        input_schema=object_schema(
                            {
                                "change_intent": string_schema(min_length=1),
                                "proposal_constraints": array_schema(
                                    string_schema(min_length=1)
                                ),
                            },
                            required=["change_intent"],
                        ),
                        output_schema=_reviewed_proposal_result_schema(),
                        output_type="ReviewedProposal",
                        upstream_input_bindings={
                            "current_strategy": {
                                "description": "需要审查的当前权威策略配置。",
                                "accepted_output_types": ["SelectedStrategyResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            },
                            "risk_constraints": {
                                "description": "用户画像或组合风险约束。",
                                "accepted_output_types": [
                                    "PortfolioRiskResult",
                                    "UserProfileResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                            "supporting_analysis": {
                                "description": "用于评估策略的模型指标、回测和组合状态。",
                                "accepted_output_types": [
                                    "ModelMetricsResult",
                                    "BacktestSummaryResult",
                                    "PortfolioAnalysisResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                        },
                        selection_requirements=[
                            "用户目标必须是审查或调整策略配置，而不是普通持仓分析。",
                            "必须存在可引用的 SelectedStrategyResult。",
                        ],
                        user_goal_examples=[
                            "审查我当前策略是否适合现在的风险偏好",
                            "把当前策略改得更稳健并形成待审批方案",
                        ],
                        negative_goal_examples=[
                            "查看当前使用的策略",
                            "分析某只股票",
                        ],
                        completion_criteria=[
                            "说明策略审查依据并返回待审批 ReviewedProposal。",
                            "不得直接激活或修改策略。",
                        ],
                        planning_notes=[
                            "查询当前策略应由能输出 SelectedStrategyResult 的能力先完成。",
                        ],
                        allowed_request_modes=["proposal"],
                        side_effect_policy={
                            "kind": "proposal_only",
                            "requires_approval": True,
                            "execution_allowed": False,
                            "commits_state": False,
                        },
                    ),
                    WorkerTaskContract(
                        task_type="review_proposal",
                        description=(
                            "审查一个已经存在的 Proposal，检查其事实依据、风险约束、权限限制、"
                            "参数完整性和执行边界。没有已有 Proposal 时不得选择该任务。"
                        ),
                        input_schema=object_schema(
                            {
                                "change_intent": string_schema(min_length=1),
                                "proposal_constraints": array_schema(
                                    string_schema(min_length=1)
                                ),
                            },
                            required=["change_intent"],
                        ),
                        output_schema=_reviewed_proposal_result_schema(),
                        output_type="ReviewedProposal",
                        upstream_input_bindings={
                            "existing_proposal": {
                                "description": "需要审查的已有待审批 Proposal。",
                                "accepted_output_types": ["ReviewedProposal"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            },
                            "current_state": {
                                "description": "用于重新校验 Proposal 的最新权威状态。",
                                "accepted_output_types": [
                                    "PortfolioAnalysisResult",
                                    "SelectedStrategyResult",
                                    "AccountStateResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                            "risk_constraints": {
                                "description": "用于重新审查的风险和权限约束。",
                                "accepted_output_types": [
                                    "PortfolioRiskResult",
                                    "UserProfileResult",
                                ],
                                "required": False,
                                "min_items": 0,
                                "max_items": 4,
                            },
                        },
                        selection_requirements=[
                            "上下文中必须存在已有 ReviewedProposal，并且用户明确要求审查、修改或重新校验该 Proposal。",
                            "用户只是确认或拒绝已有 Proposal 时不选择，应进入独立确认协议。",
                        ],
                        user_goal_examples=[
                            "重新审查刚才的调仓预案",
                            "检查这个 Proposal 是否仍符合当前风险约束",
                        ],
                        negative_goal_examples=[
                            "确认执行这个方案",
                            "取消这个方案",
                            "从零生成一个新方案",
                        ],
                        completion_criteria=[
                            "返回经过重新审查的 ReviewedProposal 和明确限制。",
                            "不得批准或执行 Proposal。",
                        ],
                        planning_notes=[
                            "existing_proposal 必须来自上游 WorkerResult，不得只传 proposal_id 文本。",
                        ],
                        allowed_request_modes=["proposal"],
                        side_effect_policy={
                            "kind": "proposal_review_only",
                            "requires_approval": True,
                            "execution_allowed": False,
                            "commits_state": False,
                        },
                        required_upstream_output_groups=[["ReviewedProposal"]],
                    ),
                ],
                input_schema=object_schema(
                    {
                        "change_intent": string_schema(min_length=1),
                        "proposal_constraints": array_schema({"type": "string"}),
                    },
                    required=["change_intent"],
                ),
                output_schema=_reviewed_proposal_result_schema(),
                output_types=["ReviewedProposal"],
                selection_requirements=[
                    "只在用户明确要求形成或审查具体状态变更 Proposal 时选择。",
                    "MainAgent 必须根据具体 task_contract 区分新建 Proposal、策略审查和已有 Proposal 审查。",
                    "任何 W05 输出都只是待审批方案，不表示已经执行。",
                ],
                non_responsibilities=[
                    "纯分析、纯解释或纯状态查看任务",
                    "原始证据检索",
                    "批准 Proposal",
                    "直接执行交易、策略激活或其他状态变更",
                ],
                side_effects=["proposal_only"],
                supports_parallel=False,
                can_generate_proposal=True,
                private_worker_prompt=(
                    "你负责按照 task_type 生成或审查待审批 Proposal。只使用任务声明的上游权威结果，"
                    "不得自行补充证券实体、风险事实或模型信号。禁止 Commit，禁止声称已经执行。"
                    "最终必须返回 ReviewedProposal WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W06,
                agent_id=REPORT_WRITER,
                role=REPORT_WRITER,
                description=(
                    "负责把已经完成的结构化 WorkerResult 组织成面向用户的最终回答或结果摘要。"
                    "W06 只能转述、压缩和编排上游事实、分析、风险或 Proposal，"
                    "不能重新查询业务数据、解析新实体、补造名称、风险结论或操作建议。"
                ),
                responsibility=(
                    "根据用户原始目标选择需要呈现的上游结果，保留来源任务、限制、不确定性和审批边界，"
                    "并输出与用户语言一致的 FinalReport。"
                ),
                accepted_task_types=["write_report", "summarize_results"],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="write_report",
                        description=(
                            "生成面向最终用户的完整回答。适用于需要把一个或多个专业 WorkerResult"
                            "整合为自然语言报告、表格或结论说明的场景。"
                        ),
                        input_schema=object_schema(
                            {
                                "report_goal": string_schema(min_length=1),
                                "reply_language": string_schema(enum=["zh", "en"]),
                            },
                            required=["report_goal", "reply_language"],
                        ),
                        output_schema=_final_report_result_schema(),
                        output_type="FinalReport",
                        upstream_input_bindings={
                            "upstream_results": {
                                "description": (
                                    "本次最终回答实际需要汇总的上游 WorkerResult。"
                                    "只引用与 report_goal 直接相关的结果。"
                                ),
                                "accepted_output_types": ["*"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 8,
                            },
                        },
                        authoritative_arg_bindings={"reply_language": "reply_language"},
                        selection_requirements=[
                            "需要向用户返回最终自然语言回答时选择。",
                            "必须通过 upstream_results 引用所有被报告使用的专业结果。",
                            "不得把 W06 当作任何专业分析、风险判断或 Proposal 生成能力。",
                        ],
                        user_goal_examples=[
                            "把上述分析整理成最终回答",
                            "汇总账户、持仓和风险结果",
                        ],
                        negative_goal_examples=[
                            "查询最新模型排名",
                            "分析组合风险",
                            "生成调仓 Proposal",
                        ],
                        completion_criteria=[
                            "输出 FinalReport，包含 source_task_ids、content 和 limitations。",
                            "正文中的实体、数值、风险和方案结论均能回溯到上游结果。",
                            "若上游是 ReviewedProposal，明确方案仍待审批且尚未执行。",
                        ],
                        planning_notes=[
                            "先完成专业 Worker，再把需要呈现的结果引用到 upstream_results。",
                            "不要为了让回答更完整而增加用户未请求的风险、建议或明细。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "presentation_only", "commits_state": False},
                    ),
                    WorkerTaskContract(
                        task_type="summarize_results",
                        description=(
                            "对已经存在的多个 WorkerResult 做紧凑摘要，适用于用户明确要求简要总结、"
                            "提炼要点或压缩已有结果；不重新执行专业分析。"
                        ),
                        input_schema=object_schema(
                            {
                                "report_goal": string_schema(min_length=1),
                                "reply_language": string_schema(enum=["zh", "en"]),
                            },
                            required=["report_goal", "reply_language"],
                        ),
                        output_schema=_final_report_result_schema(),
                        output_type="FinalReport",
                        upstream_input_bindings={
                            "upstream_results": {
                                "description": "需要压缩总结的已有结构化 WorkerResult。",
                                "accepted_output_types": ["*"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 8,
                            },
                        },
                        authoritative_arg_bindings={"reply_language": "reply_language"},
                        selection_requirements=[
                            "用户明确要求总结已有结果，而不是发起新的查询或分析时选择。",
                        ],
                        user_goal_examples=["把刚才的结果总结成三点"],
                        negative_goal_examples=["重新分析我的组合"],
                        completion_criteria=[
                            "摘要不改变上游结论，并保留关键限制和来源任务。",
                        ],
                        planning_notes=[
                            "若缺少完成用户目标所需的专业结果，应规划相应专业能力，而不是让 W06补写。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "presentation_only", "commits_state": False},
                    ),
                ],
                input_schema=object_schema(
                    {
                        "report_goal": string_schema(min_length=1),
                        "reply_language": string_schema(enum=["zh", "en"]),
                    },
                    required=["report_goal", "reply_language"],
                ),
                authoritative_arg_bindings={"reply_language": "reply_language"},
                output_schema=_final_report_result_schema(),
                output_types=["FinalReport"],
                upstream_input_bindings={
                    "upstream_results": {
                        "description": "需要汇总到最终报告的上游 WorkerResult",
                        "accepted_output_types": ["*"],
                        "required": True,
                        "min_items": 1,
                        "max_items": 8,
                    },
                },
                selection_requirements=[
                    "只负责最终表达和摘要，不承担专业事实生产。",
                    "MainAgent 应根据具体 task_contract 区分完整报告和已有结果摘要。",
                ],
                non_responsibilities=[
                    "重新查询业务数据",
                    "解析新的金融实体",
                    "根据代码、position_id、记忆或常识补充证券名称",
                    "在缺少 PortfolioRiskResult 时生成风险、集中度或适配性结论",
                    "在缺少 ReviewedProposal 时生成具体状态调整方案",
                    "修改上游业务结论",
                    "执行状态变更",
                ],
                side_effects=[],
                supports_parallel=False,
                private_worker_prompt=(
                    "你只依据上游 WorkerResult 生成最终报告或摘要。不得调用业务数据源、补造事实、"
                    "改变上游结论或越过审批边界。实体名称只能使用上游权威实体目录。"
                    "最终必须返回 FinalReport WorkerResult，并接受事实与职责边界校验。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W07,
                agent_id=SYSTEM_DIAGNOSTIC,
                role=SYSTEM_DIAGNOSTIC,
                description=(
                    "负责诊断 Agent、模型服务、数据库、图、RAG、工具调用和运行链路的系统状态。"
                    "W07 处理的是技术运行问题，不处理金融实体研究、组合分析或策略方案。"
                ),
                responsibility=(
                    "围绕明确的 diagnostic_target 检查相关组件、整理可追踪发现、区分参数缺失、"
                    "上下文缺失、工具执行失败和业务结果为空，并给出系统根因或仍缺少的诊断证据。"
                ),
                accepted_task_types=[
                    "diagnose_system",
                    "inspect_runtime",
                    "resolve_context",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="diagnose_system",
                        description=(
                            "针对用户报告的系统故障、接口失败、页面异常或组件不可用进行根因诊断。"
                        ),
                        input_schema=object_schema(
                            {
                                "diagnostic_target": string_schema(min_length=1),
                                "run_id": {"type": "string"},
                                "error_context": _free_object(),
                            },
                            required=["diagnostic_target"],
                        ),
                        output_schema=_diagnostic_result_schema(),
                        output_type="DiagnosticResult",
                        authoritative_arg_bindings={"run_id": "run_id"},
                        selection_requirements=[
                            "用户目标是定位系统、接口、数据库、模型、图、RAG或工具链路故障时选择。",
                            "业务数据为空但没有技术错误时，应优先由对应业务 Worker 返回业务结果为空。",
                        ],
                        user_goal_examples=[
                            "为什么模拟盘页面一直加载",
                            "数据库连接为什么失败",
                            "这个 Agent Run 为什么报错",
                        ],
                        negative_goal_examples=[
                            "分析我的持仓风险",
                            "查询股票新闻",
                        ],
                        completion_criteria=[
                            "返回 checked_components、findings 和可支持的 root_cause。",
                            "明确区分参数缺失、上下文缺失、工具失败和业务结果为空。",
                        ],
                        planning_notes=[
                            "只选择与 diagnostic_target 有关的诊断范围，不扩大到无关系统组件。",
                        ],
                        allowed_request_modes=["analysis"],
                        side_effect_policy={"kind": "diagnostic_read_only", "commits_state": False},
                    ),
                    WorkerTaskContract(
                        task_type="inspect_runtime",
                        description=(
                            "检查指定 Run、会话或运行时组件的状态、耗时、错误分类和执行轨迹。"
                        ),
                        input_schema=object_schema(
                            {
                                "diagnostic_target": string_schema(min_length=1),
                                "run_id": {"type": "string"},
                                "error_context": _free_object(),
                            },
                            required=["diagnostic_target"],
                        ),
                        output_schema=_diagnostic_result_schema(),
                        output_type="DiagnosticResult",
                        authoritative_arg_bindings={"run_id": "run_id"},
                        selection_requirements=[
                            "用户要求检查运行记录、耗时、Worker状态或工具调用轨迹时选择。",
                        ],
                        user_goal_examples=[
                            "检查这个Run中哪个Worker最慢",
                            "查看工具调用为什么失败",
                        ],
                        negative_goal_examples=["查询当前账户状态"],
                        completion_criteria=[
                            "返回与目标 Run 相关的组件状态和可追踪发现。",
                        ],
                        planning_notes=[
                            "run_id 由运行时绑定；没有可用 Run 时应返回上下文缺失。",
                        ],
                        allowed_request_modes=["analysis"],
                        side_effect_policy={"kind": "diagnostic_read_only", "commits_state": False},
                    ),
                    WorkerTaskContract(
                        task_type="resolve_context",
                        description=(
                            "补齐系统诊断所需的 Run、错误上下文和组件状态；无法补齐时返回明确缺失项。"
                        ),
                        input_schema=object_schema(
                            {
                                "diagnostic_target": string_schema(min_length=1),
                                "run_id": {"type": "string"},
                                "error_context": _free_object(),
                            },
                            required=["diagnostic_target"],
                        ),
                        output_schema=_diagnostic_result_schema(),
                        output_type="DiagnosticResult",
                        authoritative_arg_bindings={"run_id": "run_id"},
                        selection_requirements=[
                            "诊断目标明确，但缺少运行记录、错误上下文或组件状态时选择。",
                        ],
                        user_goal_examples=["补齐上一轮诊断需要的Run上下文"],
                        negative_goal_examples=["补齐股票实体"],
                        completion_criteria=["返回可用诊断结果或明确 need_context。"],
                        planning_notes=["不处理金融业务上下文。"],
                        allowed_request_modes=["analysis"],
                        side_effect_policy={"kind": "diagnostic_read_only", "commits_state": False},
                    ),
                ],
                input_schema=object_schema(
                    {
                        "diagnostic_target": string_schema(min_length=1),
                        "run_id": {"type": "string"},
                        "error_context": _free_object(),
                    },
                    required=["diagnostic_target"],
                ),
                authoritative_arg_bindings={"run_id": "run_id"},
                output_schema=_diagnostic_result_schema(),
                output_types=["DiagnosticResult"],
                selection_requirements=[
                    "只用于技术运行诊断。",
                    "MainAgent 应根据具体 task_contract 区分系统根因诊断、运行时检查和诊断上下文补齐。",
                ],
                non_responsibilities=[
                    "金融实体研究",
                    "组合分析",
                    "生成策略 Proposal",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你负责指定系统目标的运行诊断，严格区分参数缺失、上下文缺失、工具失败和业务结果为空。"
                    "不处理金融业务研究或策略。最终必须返回 DiagnosticResult WorkerResult。"
                ),
            ),
        ]
        cards = [
            replace(
                card,
                task_contracts=[
                    _apply_forward_semantics(card.worker_id, contract)
                    for contract in card.task_contracts
                ],
            )
            for card in cards
        ]
        self._cards_by_agent = {card.agent_id: card for card in cards}
        self._cards_by_worker = {card.worker_id: card for card in cards}

    def get(self, identifier: str) -> AgentCapabilityCard:
        key = str(identifier or "").strip().upper()
        card = self._cards_by_worker.get(key) or self._cards_by_agent.get(key)
        if card is None:
            raise KeyError(f"unknown_worker:{key}")
        return card

    def resolve_agent_id(self, identifier: str) -> str:
        return self.get(identifier).agent_id

    def resolve_worker_id(self, identifier: str) -> str:
        return self.get(identifier).worker_id

    def list_cards(self) -> list[AgentCapabilityCard]:
        return list(self._cards_by_worker.values())

    def safe_catalog(self) -> list[dict[str, Any]]:
        return [card.safe_for_coordinator() for card in self.list_cards()]

    def planning_catalog(self) -> list[dict[str, Any]]:
        """Return a detailed but context-efficient catalog for MainAgent planning.

        Full JSON output schemas remain available to deterministic validators.
        MainAgent only needs task semantics, argument shapes, upstream result
        roles, output types, examples, completion criteria, and side-effect
        boundaries. Removing duplicated result envelopes keeps the capability
        catalog usable within the model context window without weakening the
        runtime contract.
        """

        catalog: list[dict[str, Any]] = []
        for card in self.list_cards():
            task_rows: list[dict[str, Any]] = []
            for contract in card.task_contracts:
                public = contract.safe_for_coordinator()
                task_rows.append(
                    {
                        "task_type": public["task_type"],
                        "description": public["description"],
                        "args_schema": public["args_schema"],
                        "semantic_inputs_schema": public["semantic_inputs_schema"],
                        "default_args": public["default_args"],
                        "output_type": public["output_type"],
                        "runtime_bound_args": public["runtime_bound_args"],
                        "selection_requirements": public["selection_requirements"],
                        "user_goal_examples": public["user_goal_examples"],
                        "negative_goal_examples": public["negative_goal_examples"],
                        "completion_criteria": public["completion_criteria"],
                        "planning_notes": public["planning_notes"],
                        "consumes_information_slots": public["consumes_information_slots"],
                        "produces_information_slots": public["produces_information_slots"],
                        "required_context_slots": public["required_context_slots"],
                        "coverage_semantics": public["coverage_semantics"],
                        "freshness_semantics": public["freshness_semantics"],
                        "authority_level": public["authority_level"],
                        "allowed_request_modes": public["allowed_request_modes"],
                        "side_effect_policy": public["side_effect_policy"],
                        "required_upstream_output_groups": public[
                            "required_upstream_output_groups"
                        ],
                    }
                )
            catalog.append(
                {
                    "worker_id": card.worker_id,
                    "agent_id": card.agent_id,
                    "role": card.role,
                    "description": card.description,
                    "responsibility": card.responsibility,
                    "task_contracts": task_rows,
                    "output_types": list(card.output_types),
                    "selection_requirements": list(card.selection_requirements),
                    "non_responsibilities": list(card.non_responsibilities),
                    "side_effects": list(card.side_effects),
                    "supports_parallel": card.supports_parallel,
                    "can_generate_proposal": card.can_generate_proposal,
                    "missing_context_policy": card.missing_context_policy,
                }
            )
        return catalog

    def private_tool_ids(self, identifier: str, task_type: str = "") -> list[str]:
        card = self.get(identifier)
        return card.private_tools_for(task_type) if task_type else list(card.private_tool_ids)

    def private_worker_prompt(self, identifier: str) -> str:
        return self.get(identifier).private_worker_prompt

    def supports(self, identifier: str, task_type: str) -> bool:
        try:
            card = self.get(identifier)
        except KeyError:
            return False
        return str(task_type or "") in card.accepted_task_types

    def candidates_for(self, task_type: str) -> list[str]:
        task = str(task_type or "")
        return [
            card.worker_id
            for card in self.list_cards()
            if task in card.accepted_task_types
        ]

    def validate_task_args(
        self, identifier: str, args: dict[str, Any], *, task_type: str = ""
    ) -> None:
        card = self.get(identifier)
        schema = card.task_contract(task_type).input_schema if task_type else card.input_schema
        validate_schema(dict(args or {}), schema, path="$.args")

    def validate_task_inputs(
        self,
        identifier: str,
        inputs: dict[str, Any],
        *,
        task_type: str = "",
        task_id: str = "",
        output_type_by_task: dict[str, str] | None = None,
        path: str = "$.inputs",
    ) -> list[str]:
        """Validate semantic upstream bindings and derive execution dependencies.

        MainAgent owns the semantic decision by choosing ``from_task_id`` for
        each declared input role. The runtime only compiles those references
        into an ordered dependency list; it never invents an edge.
        """

        card = self.get(identifier)
        contract = card.task_contract(task_type) if task_type else None
        raw_inputs = dict(inputs or {})
        bindings = dict(
            contract.upstream_input_bindings if contract is not None
            else card.upstream_input_bindings or {}
        )
        unknown_roles = sorted(set(raw_inputs) - set(bindings))
        if unknown_roles:
            raise WorkerContractViolation(
                "unknown_upstream_input_role",
                path,
                ",".join(unknown_roles[:20]),
            )

        derived: list[str] = []
        known_outputs = dict(output_type_by_task or {})
        for role, binding in bindings.items():
            raw_value = raw_inputs.get(role, [])
            if isinstance(raw_value, dict):
                raw_items = [raw_value]
            elif isinstance(raw_value, list):
                raw_items = raw_value
            else:
                raise WorkerContractViolation(
                    "upstream_input_role_must_be_object_or_array",
                    f"{path}.{role}",
                )
            minimum = max(0, int(binding.get("min_items") or 0))
            maximum = max(minimum, int(binding.get("max_items") or 8))
            required = bool(binding.get("required"))
            if required and minimum == 0:
                minimum = 1
            if len(raw_items) < minimum:
                raise WorkerContractViolation(
                    "required_upstream_input_missing",
                    f"{path}.{role}",
                    f"min_items={minimum}",
                )
            if len(raw_items) > maximum:
                raise WorkerContractViolation(
                    "too_many_upstream_inputs",
                    f"{path}.{role}",
                    f"max_items={maximum}",
                )
            accepted = [str(item) for item in binding.get("accepted_output_types") or []]
            seen_role_ids: set[str] = set()
            for index, item in enumerate(raw_items):
                item_path = f"{path}.{role}[{index}]"
                if not isinstance(item, dict):
                    raise WorkerContractViolation(
                        "upstream_input_reference_must_be_object",
                        item_path,
                    )
                from_task_id = str(item.get("from_task_id") or "").strip()
                expected_type = str(item.get("expected_output_type") or "").strip()
                if not from_task_id:
                    raise WorkerContractViolation(
                        "upstream_input_task_id_missing",
                        f"{item_path}.from_task_id",
                    )
                if task_id and from_task_id == task_id:
                    raise WorkerContractViolation(
                        "self_dependency_not_allowed",
                        f"{item_path}.from_task_id",
                        from_task_id,
                    )
                if from_task_id in seen_role_ids:
                    raise WorkerContractViolation(
                        "duplicate_upstream_input_reference",
                        item_path,
                        from_task_id,
                    )
                seen_role_ids.add(from_task_id)
                if not expected_type:
                    raise WorkerContractViolation(
                        "upstream_input_expected_output_type_missing",
                        f"{item_path}.expected_output_type",
                    )
                if "*" not in accepted and expected_type not in accepted:
                    raise WorkerContractViolation(
                        "upstream_input_output_type_not_accepted",
                        f"{item_path}.expected_output_type",
                        f"actual={expected_type},allowed={accepted}",
                    )
                if known_outputs:
                    if from_task_id not in known_outputs:
                        raise WorkerContractViolation(
                            "unknown_upstream_input_task",
                            f"{item_path}.from_task_id",
                            from_task_id,
                        )
                    actual_type = str(known_outputs[from_task_id])
                    if expected_type != actual_type:
                        raise WorkerContractViolation(
                            "upstream_input_output_type_mismatch",
                            f"{item_path}.expected_output_type",
                            f"task={from_task_id},expected={expected_type},actual={actual_type}",
                        )
                if from_task_id not in derived:
                    derived.append(from_task_id)
        return derived

    def validate_result(self, result: GraphWorkerResult, *, task_type: str = "") -> None:
        card = self.get(result.agent_id)
        if result.output_type not in card.output_types:
            raise WorkerContractViolation(
                "undeclared_worker_output_type", "$.output_type", result.output_type
            )
        contract = card.task_contract(task_type) if task_type else None
        if contract is not None and contract.output_type and result.output_type != contract.output_type:
            raise WorkerContractViolation(
                "task_output_type_mismatch", "$.output_type",
                f"task_type={task_type},expected={contract.output_type},actual={result.output_type}",
            )
        validate_schema(
            result.safe_for_coordinator(),
            contract.output_schema if contract is not None else card.output_schema,
        )

    def resolve_task_inputs(
        self, task: GraphAgentTask, dependency_results: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Bind declared semantic inputs to exact typed WorkerResult payloads."""

        card = self.get(task.worker_id or task.assigned_agent)
        contract = card.task_contract(task.task_type)
        bindings = dict(contract.upstream_input_bindings or {})
        resolved: dict[str, Any] = {}
        for role, refs in task.inputs.items():
            binding = dict(bindings.get(role) or {})
            items: list[dict[str, Any]] = []
            for ref in refs:
                source_id = str(ref.get("from_task_id") or "")
                expected = str(ref.get("expected_output_type") or "")
                source = dependency_results.get(source_id)
                if not isinstance(source, dict):
                    raise WorkerContractViolation(
                        "upstream_result_unavailable", f"$.inputs.{role}", source_id
                    )
                actual = str(source.get("output_type") or "")
                if actual != expected:
                    raise WorkerContractViolation(
                        "upstream_result_output_type_mismatch", f"$.inputs.{role}",
                        f"task={source_id},expected={expected},actual={actual}",
                    )
                accepted = [str(v) for v in binding.get("accepted_output_types") or []]
                if accepted and "*" not in accepted and actual not in accepted:
                    raise WorkerContractViolation(
                        "upstream_result_not_accepted", f"$.inputs.{role}", actual
                    )
                payload = source.get("payload")
                if payload is None:
                    payload = source.get("data")
                items.append({
                    "from_task_id": source_id,
                    "output_type": actual,
                    "payload_schema": str(source.get("payload_schema") or f"{actual}.v1"),
                    "payload_version": str(source.get("payload_version") or "v1"),
                    "payload": dict(payload or {}) if isinstance(payload, dict) else payload,
                    "summary": str(source.get("summary") or ""),
                    "status": str(source.get("status") or ""),
                    "evidence_refs": list(source.get("evidence_refs") or []),
                    "artifact_refs": list(source.get("artifact_refs") or []),
                })
            maximum = int(binding.get("max_items") or 8)
            resolved[role] = items[0] if maximum == 1 and len(items) == 1 else items
        return resolved

    def validate_task_contract(self, task: GraphAgentTask) -> None:
        card = self.get(task.worker_id or task.assigned_agent)
        if task.assigned_agent and task.assigned_agent != card.agent_id:
            raise WorkerContractViolation(
                "worker_dispatch_mismatch",
                "$.assigned_agent",
                f"expected={card.agent_id},actual={task.assigned_agent}",
            )
        if task.task_type not in card.accepted_task_types:
            raise WorkerContractViolation(
                "unsupported_task_type_for_worker",
                "$.task_type",
                f"{card.worker_id}:{task.task_type}",
            )
        self.validate_task_args(card.worker_id, task.args, task_type=task.task_type)
        derived_dependencies = self.validate_task_inputs(
            card.worker_id,
            task.inputs,
            task_type=task.task_type,
            task_id=task.task_id,
        )
        if derived_dependencies != list(task.dependency_task_ids):
            raise WorkerContractViolation(
                "derived_dependency_mismatch",
                "$.dependency_task_ids",
                f"derived={derived_dependencies},actual={task.dependency_task_ids}",
            )
        contract = card.task_contract(task.task_type)
        if contract.output_type and task.expected_output_type != contract.output_type:
            raise WorkerContractViolation(
                "task_contract_output_type_mismatch",
                "$.expected_output_type",
                f"expected={contract.output_type},actual={task.expected_output_type}",
            )
        if task.expected_output_type not in card.output_types:
            raise WorkerContractViolation(
                "unexpected_task_output_type",
                "$.expected_output_type",
                task.expected_output_type,
            )

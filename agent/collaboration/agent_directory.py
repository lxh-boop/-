from __future__ import annotations

from dataclasses import replace
from typing import Any

from .completion import compile_completion_contract, validate_completion_report
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
EVIDENCE_COLLECTOR = "EVIDENCE_COLLECTOR"
EVIDENCE_RETRIEVER = EVIDENCE_COLLECTOR  # compatibility alias
PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
GRAPH_RELATION_RETRIEVER = "GRAPH_RELATION_RETRIEVER"
GRAPH_IMPACT_ANALYST = GRAPH_RELATION_RETRIEVER  # compatibility alias
RISK_ANALYST = "RISK_ANALYST"
STRATEGY_GUARD = "STRATEGY_GUARD"
REPORT_WRITER = "REPORT_WRITER"
SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"
DATABASE_WRITER = "DATABASE_WRITER"
GRAPH_CONTEXT_MANAGER = DATABASE_WRITER  # compatibility alias
ENTITY_ANALYST = "ENTITY_ANALYST"

W01 = "W01"
W02 = "W02"
W03 = "W03"
W04 = "W04"
W05 = "W05"
W06 = "W06"
W07 = "W07"
W08 = "W08"
W09 = "W09"


# Information-slot semantics used by goal-constrained forward planning.
#
# These declarations are business-capability metadata, not a fixed Worker chain.
# MainAgent starts from the context and information already available, enumerates
# task contracts whose requirements are currently satisfiable, and selects only
# tasks that contribute to still-unmet GoalContract slots or unlock a necessary
# downstream capability.
_FORWARD_TASK_SEMANTICS: dict[tuple[str, str], dict[str, Any]] = {
    (W01, "collect_external_evidence"): {
        "consumes_information_slots": ["authoritative_financial_entities", "collection_goal"],
        "produces_information_slots": ["entity_external_evidence", "evidence_source_records"],
        "required_context_slots": ["authoritative_financial_entities"],
        "coverage_semantics": {"scope": "entity_ref_set", "minimum_entities": 1, "partial_results_allowed": True},
        "freshness_semantics": {"policy": "respect_requested_time_range_or_latest"},
        "authority_level": "external_evidence_with_source_records",
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
    (W08, "write_portfolio_graph_context"): {
        "consumes_information_slots": ["current_portfolio_state"],
        "produces_information_slots": ["portfolio_graph_context", "portfolio_snapshot_ref"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_portfolio_state", "write_scope": "database"},
        "freshness_semantics": {"policy": "inherit_portfolio_as_of_time"},
        "authority_level": "database_write_result",
    },
    (W08, "write_evidence_graph_context"): {
        "consumes_information_slots": ["entity_external_evidence"],
        "produces_information_slots": ["evidence_graph_context", "evidence_graph_refs"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_evidence_collection", "write_scope": "database"},
        "freshness_semantics": {"policy": "inherit_evidence_time_range"},
        "authority_level": "database_write_result",
    },
    (W03, "retrieve_financial_relations"): {
        "consumes_information_slots": ["authoritative_graph_refs", "optional_source_graph_context", "optional_target_graph_context"],
        "produces_information_slots": ["financial_relation_paths", "related_graph_objects"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "declared_source_and_target_graph_contexts", "interpretation_performed": False},
        "freshness_semantics": {"policy": "inherit_upstream_as_of_time"},
        "authority_level": "financial_graph_relation_retrieval",
    },
    (W09, "analyze_financial_entities"): {
        "consumes_information_slots": ["entity_external_evidence", "optional_entity_model_signals", "optional_financial_relation_paths"],
        "produces_information_slots": ["entity_analysis", "entity_analysis_uncertainty"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_entity_set", "claims_require_upstream_support": True},
        "freshness_semantics": {"policy": "inherit_upstream_time_range"},
        "authority_level": "specialist_entity_analysis",
    },
    (W09, "compare_financial_entities"): {
        "consumes_information_slots": ["entity_external_evidence", "optional_entity_model_signals", "optional_financial_relation_paths"],
        "produces_information_slots": ["comparative_entity_analysis", "entity_analysis_uncertainty"],
        "required_context_slots": [],
        "coverage_semantics": {"scope": "provided_entity_set", "minimum_entities": 2, "claims_require_upstream_support": True},
        "freshness_semantics": {"policy": "inherit_upstream_time_range"},
        "authority_level": "specialist_entity_analysis",
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


def _evidence_collection_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "EvidenceCollectionResult",
        data_schema=object_schema(
            {
                "entity_refs": array_schema(_free_object()),
                "collection_goal": {"type": "string"},
                "results": array_schema(_free_object()),
                "record_count": {"type": "integer"},
                "source_count": {"type": "integer"},
                "write_performed": {"type": "boolean"},
            },
            required=["entity_refs", "collection_goal", "results", "record_count", "source_count", "write_performed"],
            additional_properties=True,
        ),
        completion_required=True,
    )


def _portfolio_graph_context_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "PortfolioGraphContextResult",
        data_schema=object_schema(
            {
                "portfolio_ref": _free_object(),
                "holding_refs": array_schema(_free_object()),
                "unresolved_positions": array_schema(_free_object()),
                "write_summary": _free_object(),
                "source_task_ids": _task_ids(),
            },
            required=["portfolio_ref", "holding_refs", "unresolved_positions", "write_summary", "source_task_ids"],
            additional_properties=True,
        ),
    )


def _evidence_graph_context_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "EvidenceGraphContextResult",
        data_schema=object_schema(
            {
                "evidence_refs": array_schema(_free_object()),
                "written_record_count": {"type": "integer"},
                "failed_record_count": {"type": "integer"},
                "write_results": array_schema(_free_object()),
                "source_task_ids": _task_ids(),
            },
            required=["evidence_refs", "written_record_count", "failed_record_count", "write_results", "source_task_ids"],
            additional_properties=True,
        ),
    )


def _graph_relation_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "GraphRelationResult",
        data_schema=object_schema(
            {
                "source_task_ids": array_schema({"type": "string"}),
                "target_task_ids": array_schema({"type": "string"}),
                "source_refs": array_schema(_free_object()),
                "target_refs": array_schema(_free_object()),
                "relation_paths": array_schema(_free_object()),
                "relation_summary": _free_object(),
            },
            required=["source_task_ids", "target_task_ids", "source_refs", "target_refs", "relation_paths", "relation_summary"],
            additional_properties=True,
        ),
    )


def _entity_analysis_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "EntityAnalysisResult",
        data_schema=object_schema(
            {
                "entity_refs": array_schema(_free_object()),
                "facts": array_schema(_free_object()),
                "analysis": array_schema(_free_object()),
                "model_signals": array_schema(_free_object()),
                "relation_interpretations": array_schema(_free_object()),
                "uncertainties": array_schema(_free_object()),
                "conclusion": {"type": "string"},
                "source_task_ids": array_schema({"type": "string"}),
            },
            required=["entity_refs", "facts", "analysis", "uncertainties", "conclusion", "source_task_ids"],
            additional_properties=True,
        ),
        completion_required=True,
    )


def _portfolio_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "PortfolioAnalysisResult",
        data_schema=object_schema(
            {
                "entity_catalog": array_schema(_free_object()),
                "display_positions": array_schema(_free_object()),
                "account_snapshot": _free_object(),
                "portfolio_totals": _free_object(),
                "portfolio_summary": _free_object(),
                "unresolved_positions": array_schema(_free_object()),
                "as_of_time": {"type": "string"},
                "graph_snapshot_materialized": {"type": "boolean"},
            },
            required=[
                "entity_catalog",
                "display_positions",
                "account_snapshot",
                "portfolio_totals",
                "portfolio_summary",
                "unresolved_positions",
                "graph_snapshot_materialized",
            ],
            additional_properties=True,
        ),
    )


def _portfolio_graph_snapshot_result_schema() -> dict[str, Any]:
    return worker_result_schema(
        "PortfolioGraphSnapshotResult",
        data_schema=object_schema(
            {
                "portfolio_ref": _free_object(),
                "holding_refs": array_schema(_free_object()),
                "unresolved_positions": array_schema(_free_object()),
                "graph_write_summary": _free_object(),
                "source_task_ids": _task_ids(),
            },
            required=[
                "portfolio_ref",
                "holding_refs",
                "unresolved_positions",
                "graph_write_summary",
                "source_task_ids",
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
        completion_required=True,
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
                agent_id=EVIDENCE_COLLECTOR,
                role=EVIDENCE_COLLECTOR,
                description=(
                    "负责查找一个或多个已确认金融实体的外部证据，并对证据进行整理、去重、排序和来源核验。"
                    "实体集合可以只包含一个元素。W01 不分析证据含义，不写数据库。"
                ),
                responsibility=(
                    "根据实体集合、收集目标和时间范围返回可追踪的 EvidenceCollectionResult。"
                ),
                accepted_task_types=["collect_external_evidence"],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="collect_external_evidence",
                        description=(
                            "查找一个或多个权威金融实体的新闻、公告、研报及其他外部证据，"
                            "返回按实体归属组织的证据集合。"
                        ),
                        input_schema=object_schema(
                            {
                                "entity_ref_ids": _ref_ids(),
                                "collection_goal": string_schema(min_length=1),
                                "time_range": _free_object(),
                                "source_scope": array_schema({"type": "string"}),
                                "top_k": {"type": "integer"},
                            },
                            required=["entity_ref_ids", "collection_goal"],
                        ),
                        output_schema=_evidence_collection_result_schema(),
                        output_type="EvidenceCollectionResult",
                        authoritative_arg_bindings={"entity_ref_ids": "focus_ref_ids"},
                        selection_requirements=[
                            "用户目标需要查找一个或多个已解析金融实体的外部证据。",
                            "实体分析、组合风险、关系解释或方案生成不得由 W01 承担。",
                        ],
                        user_goal_examples=[
                            "查找贵州茅台最近的公告和新闻",
                            "收集600519和000858同期的外部证据",
                            "分析600519时先收集可用外部证据",
                        ],
                        negative_goal_examples=[
                            "解释这些新闻对公司的意义",
                            "这些新闻会怎样影响我的持仓",
                            "给我一个调仓方案",
                        ],
                        completion_criteria=[
                            "按实体返回证据记录、来源、时间范围和明确限制。",
                            "未检索到证据时返回业务结果为空，不得补造。",
                            "不得写入 Neo4j 或其他数据库。",
                        ],
                        completion_report_required=True,
                        planning_notes=[
                            "单实体与多实体使用同一个能力；单实体只是 entity_ref_ids 只有一个元素。",
                            "W01 内部工具不会暴露给 MainAgent。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=[
                            "evidence.search_news",
                            "evidence.search_rag",
                            "evidence.finalize_collection",
                        ],
                    )
                ],
                input_schema=object_schema(
                    {
                        "entity_ref_ids": _ref_ids(),
                        "collection_goal": string_schema(min_length=1),
                        "time_range": _free_object(),
                        "source_scope": array_schema({"type": "string"}),
                        "top_k": {"type": "integer"},
                    },
                    required=["entity_ref_ids", "collection_goal"],
                ),
                authoritative_arg_bindings={"entity_ref_ids": "focus_ref_ids"},
                output_schema=_evidence_collection_result_schema(),
                output_types=["EvidenceCollectionResult"],
                selection_requirements=[
                    "只用于收集已确认金融实体集合的外部证据。",
                ],
                non_responsibilities=[
                    "解释或分析证据含义",
                    "查找金融图关系",
                    "读取用户账户或持仓",
                    "评估组合风险",
                    "生成 Proposal",
                    "写入数据库",
                ],
                side_effects=[],
                private_tool_ids=[
                    "evidence.search_news",
                    "evidence.search_rag",
                    "evidence.finalize_collection",
                ],
                private_worker_prompt=(
                    "你是外部证据收集 Worker。只负责收集、整理、去重、排序和核验来源；"
                    "不得解释证据含义、生成风险或方案、写入数据库。"
                    "最终必须返回 EvidenceCollectionResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W02,
                agent_id=PORTFOLIO_ANALYST,
                role="INTERNAL_SYSTEM_RETRIEVER",
                description=(
                    "负责读取并标准化本系统已经存在的权威结构化事实，包括证券预测、全市场排名、"
                    "模型指标、回测摘要、当前策略、用户画像、账户资金和组合持仓。"
                    "W02 是纯内部事实查询 Worker，不检索外部新闻，不写入 Neo4j，不形成风险结论，"
                    "不生成买卖建议或 Proposal。"
                ),
                responsibility=(
                    "根据每个 task_type 调用对应只读内部能力，把结果转换为稳定强类型 WorkerResult。"
                    "证券身份只通过已有 Neo4j 身份表进行只读解析；组合图快照由 W08 单独物化。"
                ),
                accepted_task_types=[
                    "query_stock_prediction",
                    "query_latest_ranking",
                    "query_model_metrics",
                    "query_backtest_summary",
                    "query_selected_strategy",
                    "query_portfolio_state",
                    "query_account_state",
                    "query_user_profile",
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
                    WorkerTaskContract(
                        task_type="query_portfolio_state",
                        description=(
                            "只读取当前用户账户对应的权威组合和持仓事实，返回账户摘要、持仓明细、"
                            "已存在的证券实体引用和未解析项。该任务不创建或更新 portfolio_snapshot，"
                            "不写入 Neo4j，也不形成风险或调整结论。"
                        ),
                        input_schema=object_schema(
                            {
                                "user_id": string_schema(min_length=1),
                                "as_of_time": {"type": "string"},
                            },
                            required=["user_id"],
                        ),
                        output_schema=_portfolio_result_schema(),
                        output_type="PortfolioAnalysisResult",
                        authoritative_arg_bindings={
                            "user_id": "user_id",
                            "as_of_time": "as_of_time",
                        },
                        selection_requirements=[
                            "用户需要当前组合、持仓、仓位或组合市值事实时选择。",
                            "后续风险或 Proposal 能力需要权威组合状态输入时可以选择。",
                            "后续能力明确需要 portfolio_snapshot GraphRef 或图路径时，还应另行选择 W08。",
                        ],
                        user_goal_examples=[
                            "查看我当前的模拟盘持仓",
                            "读取当前组合作为风险分析的事实输入",
                        ],
                        negative_goal_examples=[
                            "把当前组合写入金融图并生成 portfolio_ref",
                            "分析这些新闻如何影响我的持仓图路径",
                            "直接给出调仓方案",
                        ],
                        completion_criteria=[
                            "返回 entity_catalog、display_positions、account_snapshot、portfolio_totals、portfolio_summary、unresolved_positions 和数据时间。",
                            "graph_snapshot_materialized 必须为 False。",
                            "证券身份来自已有统一实体链路；无法解析时明确列入 unresolved_positions。",
                        ],
                        planning_notes=[
                            "这是原子化只读能力；不得把读取组合和派生图写入合并成一个任务。",
                            "需要组合 GraphRef 时由 W08 消费本结果并物化快照。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                        private_tool_ids=["internal.portfolio.get_state"],
                    ),
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
                side_effects=[],
                private_tool_ids=[
                    "internal.prediction.get_stock", "internal.ranking.get_latest",
                    "internal.model.get_metrics", "internal.backtest.get_summary",
                    "internal.strategy.get_selected", "internal.portfolio.get_state",
                    "internal.account.get_state", "internal.user_profile.get",
                ],
                private_worker_prompt=(
                    "你是本系统内部权威数据查询 Worker。严格根据 task_type 调用对应只读私有能力，"
                    "返回任务合同指定的强类型结果。不得写入 Neo4j，不得物化组合图快照，"
                    "不得检索外部新闻，不得生成风险结论、建议或 Proposal。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W08,
                agent_id=DATABASE_WRITER,
                role=DATABASE_WRITER,
                description="负责写数据库。",
                responsibility="执行已注册的非交易性数据库写入任务。",
                accepted_task_types=[
                    "write_portfolio_graph_context",
                    "write_evidence_graph_context",
                ],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="write_portfolio_graph_context",
                        description="把权威组合状态写入数据库，生成可供关系查找使用的组合图上下文。",
                        input_schema=object_schema(
                            {"user_id": string_schema(min_length=1), "as_of_time": {"type": "string"}},
                            required=["user_id"],
                        ),
                        output_schema=_portfolio_graph_context_result_schema(),
                        output_type="PortfolioGraphContextResult",
                        authoritative_arg_bindings={"user_id": "user_id", "as_of_time": "as_of_time"},
                        upstream_input_bindings={
                            "portfolio_state": {
                                "description": "需要写入数据库的权威组合状态。",
                                "accepted_output_types": ["PortfolioAnalysisResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            }
                        },
                        selection_requirements=[
                            "后续任务明确需要组合图上下文或 portfolio_ref 时选择。",
                            "必须存在一个上游 PortfolioAnalysisResult。",
                        ],
                        user_goal_examples=["保存当前组合图上下文，供关系查找使用"],
                        negative_goal_examples=["只查看当前持仓", "执行模拟盘交易"],
                        completion_criteria=["返回 portfolio_ref、holding_refs、写入结果和来源任务。"],
                        planning_notes=["W08 不读取组合，输入必须来自声明的上游结果。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_database_write", "trading_state_write": False},
                        private_tool_ids=["database.write_portfolio_graph_context"],
                        required_upstream_output_groups=[["PortfolioAnalysisResult"]],
                    ),
                    WorkerTaskContract(
                        task_type="write_evidence_graph_context",
                        description="把外部证据集合写入数据库，生成可供关系查找使用的证据图上下文。",
                        input_schema=object_schema({}, required=[], additional_properties=True),
                        output_schema=_evidence_graph_context_result_schema(),
                        output_type="EvidenceGraphContextResult",
                        upstream_input_bindings={
                            "evidence_collection": {
                                "description": "需要写入数据库的外部证据集合。",
                                "accepted_output_types": ["EvidenceCollectionResult"],
                                "required": True,
                                "min_items": 1,
                                "max_items": 1,
                            }
                        },
                        selection_requirements=[
                            "后续任务明确需要证据 GraphRef 或图关系时选择。",
                            "必须存在一个上游 EvidenceCollectionResult。",
                        ],
                        user_goal_examples=["把已收集的证据写入图数据库，供关系查找使用"],
                        negative_goal_examples=["只收集新闻", "执行模拟盘交易"],
                        completion_criteria=["返回 evidence_refs、写入数量、失败数量和来源任务。"],
                        planning_notes=["W08 不收集或解释证据。"],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "derived_database_write", "trading_state_write": False},
                        private_tool_ids=["database.write_evidence_graph_context"],
                        required_upstream_output_groups=[["EvidenceCollectionResult"]],
                    ),
                ],
                input_schema=object_schema({}, required=[], additional_properties=True),
                output_schema=_portfolio_graph_context_result_schema(),
                output_types=["PortfolioGraphContextResult", "EvidenceGraphContextResult"],
                selection_requirements=[
                    "只在目标需要将非交易性数据写入数据库时选择。",
                    "MainAgent 必须根据具体 task_contract 声明上游结果。",
                ],
                non_responsibilities=[
                    "读取或分析业务数据",
                    "生成业务结论或 Proposal",
                    "执行模拟盘订单、现金或持仓写入",
                ],
                side_effects=["derived_database_write"],
                supports_parallel=True,
                can_generate_proposal=False,
                private_tool_ids=[
                    "database.write_portfolio_graph_context",
                    "database.write_evidence_graph_context",
                ],
                private_worker_prompt=(
                    "你是数据库写入 Worker。只能执行 task_type 对应的已注册非交易性写入；"
                    "不得分析数据或执行模拟盘交易。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W03,
                agent_id=GRAPH_RELATION_RETRIEVER,
                role=GRAPH_RELATION_RETRIEVER,
                description=(
                    "负责从金融图中查找来源对象集合与目标对象集合之间的关系路径。"
                    "W03 只查找关系，不解释关系意味着什么。"
                ),
                responsibility="返回可追踪的 GraphRelationResult。",
                accepted_task_types=["retrieve_financial_relations"],
                task_contracts=[
                    WorkerTaskContract(
                        task_type="retrieve_financial_relations",
                        description=(
                            "在权威金融图对象集合之间查找直接或间接关系路径。"
                            "来源和目标可以来自当前 GraphRef，也可以来自上游数据库写入结果。"
                        ),
                        input_schema=object_schema(
                            {
                                "relation_goal": string_schema(min_length=1),
                                "source_ref_ids": _ref_ids(min_items=1),
                                "target_ref_ids": _ref_ids(min_items=1),
                            },
                            required=["relation_goal"],
                        ),
                        output_schema=_graph_relation_result_schema(),
                        output_type="GraphRelationResult",
                        upstream_input_bindings={
                            "source_graph_context": {
                                "description": "可选的来源图上下文。",
                                "accepted_output_types": ["EvidenceGraphContextResult", "PortfolioGraphContextResult"],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                            "target_graph_context": {
                                "description": "可选的目标图上下文。",
                                "accepted_output_types": ["EvidenceGraphContextResult", "PortfolioGraphContextResult"],
                                "required": False,
                                "min_items": 0,
                                "max_items": 8,
                            },
                        },
                        selection_requirements=[
                            "用户目标需要知道哪些对象有关、关系路径是什么。",
                            "来源和目标必须能够由权威 GraphRef 或声明的上游图上下文确定。",
                            "需要判断影响方向、强度或业务含义时，还应由 W09 消费本结果。",
                        ],
                        user_goal_examples=[
                            "查找600519和000858之间的金融图关系",
                            "这些新闻和我的哪些持仓存在图关系",
                            "查找证据到组合持仓的关系路径",
                        ],
                        negative_goal_examples=[
                            "这些新闻对公司的影响是什么",
                            "给我具体减仓方案",
                        ],
                        completion_criteria=[
                            "输出来源、目标、关系路径和路径摘要。",
                            "未找到路径时明确返回业务结果为空。",
                            "不得把关系存在解释为因果影响。",
                        ],
                        planning_notes=[
                            "已有实体 GraphRef 可直接用于关系查找，不强制经过 W08。",
                            "只有外部证据集合或组合状态尚未形成图上下文时，才需要先选择 W08。",
                            "W03 只做图关系查找，不做业务解释。",
                        ],
                        allowed_request_modes=["analysis", "proposal"],
                        side_effect_policy={"kind": "read_only", "commits_state": False},
                    )
                ],
                input_schema=object_schema(
                    {
                        "relation_goal": string_schema(min_length=1),
                        "source_ref_ids": _ref_ids(min_items=1),
                        "target_ref_ids": _ref_ids(min_items=1),
                    },
                    required=["relation_goal"],
                ),
                output_schema=_graph_relation_result_schema(),
                output_types=["GraphRelationResult"],
                selection_requirements=["只用于金融图关系查找。"],
                non_responsibilities=[
                    "收集外部证据",
                    "解释关系的业务含义",
                    "评估组合风险",
                    "生成 Proposal",
                    "写入数据库",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你是金融图关系查找 Worker。只返回关系是否存在、路径、涉及对象和证据引用；"
                    "不得判断利好利空、影响强度、组合风险或建议。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W09,
                agent_id=ENTITY_ANALYST,
                role=ENTITY_ANALYST,
                description=(
                    "负责基于上游证据、模型事实和可选关系结果分析一个或多个金融实体。"
                ),
                responsibility=(
                    "区分事实、分析、模型信号、关系解释和不确定性，输出 EntityAnalysisResult。"
                ),
                accepted_task_types=["analyze_financial_entities", "compare_financial_entities"],
                task_contracts=[
                    *[
                        WorkerTaskContract(
                            task_type=task_type,
                            description=description_text,
                            input_schema=object_schema(
                                {"analysis_goal": string_schema(min_length=1)},
                                required=["analysis_goal"],
                            ),
                            output_schema=_entity_analysis_result_schema(),
                            output_type="EntityAnalysisResult",
                            upstream_input_bindings={
                                "evidence": {
                                    "description": "W01 收集的外部证据集合。",
                                    "accepted_output_types": ["EvidenceCollectionResult"],
                                    "required": True,
                                    "min_items": 1,
                                    "max_items": 8,
                                },
                                "model_facts": {
                                    "description": "可选的内部模型或结构化事实。",
                                    "accepted_output_types": [
                                        "ModelPredictionResult", "RankingResult", "ModelMetricsResult",
                                        "BacktestSummaryResult", "SelectedStrategyResult",
                                    ],
                                    "required": False,
                                    "min_items": 0,
                                    "max_items": 8,
                                },
                                "relation_context": {
                                    "description": "可选的金融图关系查找结果。",
                                    "accepted_output_types": ["GraphRelationResult"],
                                    "required": False,
                                    "min_items": 0,
                                    "max_items": 8,
                                },
                            },
                            selection_requirements=selection_requirements,
                            user_goal_examples=user_examples,
                            negative_goal_examples=[
                                "只查找新闻和公告",
                                "只查找图关系路径",
                                "分析我的组合风险",
                                "生成调仓方案",
                            ],
                            completion_criteria=[
                                "所有事实和分析能够回溯到上游结果。",
                                "关系存在不得直接等同于因果影响。",
                                "不得生成组合风险或操作建议。",
                            ],
                            completion_report_required=True,
                            planning_notes=["W09 不自行检索证据或查询数据库。"],
                            allowed_request_modes=["analysis", "proposal"],
                            side_effect_policy={"kind": "read_only", "commits_state": False},
                            required_upstream_output_groups=[["EvidenceCollectionResult"]],
                        )
                        for task_type, description_text, selection_requirements, user_examples in [
                            (
                                "analyze_financial_entities",
                                "基于上游材料分析一个或多个金融实体本身的状态和证据含义。",
                                ["用户要求解释或分析金融实体本身时选择。"],
                                ["分析600519", "分析贵州茅台近期情况"],
                            ),
                            (
                                "compare_financial_entities",
                                "基于同一范围的上游材料比较多个金融实体。",
                                ["用户明确要求比较两个或多个金融实体时选择。"],
                                ["比较贵州茅台和五粮液", "对比600519和000858"],
                            ),
                        ]
                    ]
                ],
                input_schema=object_schema(
                    {"analysis_goal": string_schema(min_length=1)},
                    required=["analysis_goal"],
                ),
                output_schema=_entity_analysis_result_schema(),
                output_types=["EntityAnalysisResult"],
                required_upstream_output_groups=[["EvidenceCollectionResult"]],
                selection_requirements=["只用于金融实体层面的分析或比较。"],
                non_responsibilities=[
                    "自行收集证据",
                    "自行查询内部数据库",
                    "查找图关系",
                    "分析用户组合风险",
                    "生成 Proposal",
                    "写入数据库",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你是金融实体分析 Worker。只能消费上游结构化结果，区分事实、分析和不确定性；"
                    "不得自行检索、查询数据库、分析组合风险或生成方案。"
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
                                "description": "与风险问题直接相关的实体分析或关系查找结果。",
                                "accepted_output_types": [
                                    "EntityAnalysisResult",
                                    "GraphRelationResult",
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
                                    "EntityAnalysisResult",
                                    "GraphRelationResult",
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
                            "EntityAnalysisResult",
                            "GraphRelationResult",
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
                                    "支持调整方向和参数的模型信号、实体分析、关系结果、用户画像、"
                                    "回测摘要或其他系统权威事实。"
                                ),
                                "accepted_output_types": [
                                    "RankingResult",
                                    "ModelPredictionResult",
                                    "EntityAnalysisResult",
                                    "GraphRelationResult",
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
                        completion_report_required=True,
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
                        completion_report_required=True,
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

    def completion_contract_for_task(self, task: GraphAgentTask) -> dict[str, Any]:
        card = self.get(task.worker_id or task.assigned_agent)
        contract = card.task_contract(task.task_type)
        return compile_completion_contract(task, contract)

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
        if contract is not None and contract.completion_report_required:
            completion_contract = dict(result.metadata.get("completion_contract") or {})
            if not completion_contract:
                raise WorkerContractViolation(
                    "worker_completion_contract_missing",
                    "$.metadata.completion_contract",
                )
            validate_completion_report(result.completion, completion_contract)

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

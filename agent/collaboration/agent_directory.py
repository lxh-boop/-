from __future__ import annotations

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


def _task_ids(*, min_items: int = 1) -> dict[str, Any]:
    return array_schema(string_schema(min_length=1), min_items=min_items, max_items=8)


def _ref_ids(*, min_items: int = 1) -> dict[str, Any]:
    return array_schema(string_schema(min_length=1), min_items=min_items, max_items=30)


def _free_object() -> dict[str, Any]:
    return object_schema({}, additional_properties=True)


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
                    "围绕一个或多个已确认金融实体完成证据整合、研究与比较，"
                    "内部自行决定所需的市场证据读取步骤。"
                ),
                responsibility=(
                    "接收权威金融对象引用和研究问题，形成独立、可追踪的实体研究结果。"
                ),
                accepted_task_types=[
                    "retrieve_evidence",
                    "analyze_entity_evidence",
                    "compare_entity_evidence",
                    "ingest_evidence",
                    "resolve_context",
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
                authoritative_arg_bindings={
                    "focus_ref_ids": "focus_ref_ids",
                },
                selection_requirements=[
                    "用于已解析金融实体的独立研究、比较或证据整合。",
                    "不因为用户只请求实体分析而自动扩展到组合、持仓或组合风险。",
                ],
                output_schema=worker_result_schema(
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
                ),
                output_types=["EntityResearchResult"],
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
                    "你负责金融实体研究。仅围绕任务给定的 GraphRef 和研究问题工作；"
                    "自行选择必要的私有证据工具；不得读取用户组合、生成 Proposal 或执行状态变更。"
                    "最终必须返回 EntityResearchResult WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W02,
                agent_id=PORTFOLIO_ANALYST,
                role="INTERNAL_SYSTEM_RETRIEVER",
                description=(
                    "读取本系统已经存在的权威结构化数据，包括模型预测、排名、"
                    "模型指标、回测、当前策略、用户画像、账户与持仓。"
                ),
                responsibility=(
                    "只查询并标准化系统内部事实，不检索外部新闻，不生成风险结论、"
                    "买卖建议、Proposal 或任何业务写入。"
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
                        description="查询已解析证券在最新模型预测排名中的结构化结果。",
                        input_schema=object_schema(
                            {
                                "focus_ref_ids": _ref_ids(),
                                "top_k": {
                                    "type": "integer",
                                    "default": 10,
                                    "description": "默认值为10；用户未指定时使用10。",
                                },
                                "model_name": {
                                    "type": "string",
                                    "description": "仅在用户明确指定模型时填写，否则省略并读取当前激活模型。",
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
                            "用户要求分析、查询或解释某只证券的模型预测、评分、排名或TopK状态时选择。",
                        ],
                        private_tool_ids=["internal.prediction.get_stock"],
                    ),
                    WorkerTaskContract(
                        task_type="query_latest_ranking",
                        description="查询本系统最新预测排名。",
                        input_schema=object_schema(
                            {
                                "top_k": {
                                    "type": "integer",
                                    "default": 10,
                                    "description": "默认值为10；用户未指定时使用10。",
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
                        private_tool_ids=["internal.ranking.get_latest"],
                    ),
                    WorkerTaskContract(
                        task_type="query_model_metrics",
                        description="查询当前模型指标。",
                        input_schema=object_schema({"model_name": {"type": "string"}}, required=[]),
                        output_schema=worker_result_schema("ModelMetricsResult", data_schema=_free_object()),
                        output_type="ModelMetricsResult",
                        private_tool_ids=["internal.model.get_metrics"],
                    ),
                    WorkerTaskContract(
                        task_type="query_backtest_summary",
                        description="查询模型或策略的历史回测摘要。",
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
                        private_tool_ids=["internal.backtest.get_summary"],
                    ),
                    WorkerTaskContract(
                        task_type="query_selected_strategy",
                        description="查询当前选定策略配置。",
                        input_schema=object_schema({}, required=[]),
                        output_schema=worker_result_schema("SelectedStrategyResult", data_schema=_free_object()),
                        output_type="SelectedStrategyResult",
                        private_tool_ids=["internal.strategy.get_selected"],
                    ),
                    *[
                        WorkerTaskContract(
                            task_type=task_type,
                            description="读取当前用户的权威组合快照。",
                            input_schema=object_schema(
                                {
                                    "user_id": string_schema(min_length=1),
                                    "as_of_time": {"type": "string"},
                                    "portfolio_ref_ids": _ref_ids(min_items=0),
                                },
                                required=["user_id"],
                            ),
                            output_schema=worker_result_schema(
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
                            ),
                            output_type="PortfolioAnalysisResult",
                            authoritative_arg_bindings={"user_id": "user_id", "as_of_time": "as_of_time"},
                            private_tool_ids=["internal.portfolio.get_state"],
                        )
                        for task_type in [
                            "query_portfolio_state", "load_portfolio_snapshot", "analyze_portfolio",
                            "analyze_portfolio_fit", "compare_portfolios", "resolve_context",
                        ]
                    ],
                    WorkerTaskContract(
                        task_type="query_account_state",
                        description="查询当前用户账户资金摘要。",
                        input_schema=object_schema({"user_id": string_schema(min_length=1)}, required=["user_id"]),
                        output_schema=worker_result_schema("AccountStateResult", data_schema=_free_object()),
                        output_type="AccountStateResult",
                        authoritative_arg_bindings={"user_id": "user_id"},
                        private_tool_ids=["internal.account.get_state"],
                    ),
                    WorkerTaskContract(
                        task_type="query_user_profile",
                        description="查询当前用户的权威风险画像与偏好。",
                        input_schema=object_schema({"user_id": string_schema(min_length=1)}, required=["user_id"]),
                        output_schema=worker_result_schema("UserProfileResult", data_schema=_free_object()),
                        output_type="UserProfileResult",
                        authoritative_arg_bindings={"user_id": "user_id"},
                        private_tool_ids=["internal.user_profile.get"],
                    ),
                ],
                input_schema=object_schema({}, required=[], additional_properties=True),
                output_schema=worker_result_schema("PortfolioAnalysisResult", data_schema=_free_object()),
                output_types=[
                    "ModelPredictionResult", "RankingResult", "ModelMetricsResult",
                    "BacktestSummaryResult", "SelectedStrategyResult",
                    "PortfolioAnalysisResult", "AccountStateResult", "UserProfileResult",
                ],
                selection_requirements=[
                    "用于查询本系统内部权威数据；同一DAG可创建多个W02任务，但每个任务必须声明独立task_type和output_type。",
                    "普通证券综合分析至少查询对应证券的ModelPredictionResult；组合、账户和画像仅在用户目标需要时查询。",
                ],
                non_responsibilities=[
                    "外部新闻、公告或研报检索", "组合风险结论", "新闻影响判断",
                    "买卖建议", "生成或执行调整方案", "修改任何系统数据",
                ],
                side_effects=["derived_portfolio_graph_snapshot_only"],
                private_tool_ids=[
                    "internal.prediction.get_stock", "internal.ranking.get_latest",
                    "internal.model.get_metrics", "internal.backtest.get_summary",
                    "internal.strategy.get_selected", "internal.portfolio.get_state",
                    "internal.account.get_state", "internal.user_profile.get",
                ],
                private_worker_prompt=(
                    "你是本系统内部权威数据查询Worker。根据task_type只调用对应的只读私有工具，"
                    "返回任务合同指定的强类型结果。不得检索外部新闻，不得生成风险结论、建议或写操作。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W03,
                agent_id=GRAPH_IMPACT_ANALYST,
                role=GRAPH_IMPACT_ANALYST,
                description=(
                    "基于上游实体研究结果与组合状态结果，分析源对象到当前组合的可追踪影响路径。"
                ),
                responsibility=(
                    "只解释已有源分析和目标组合之间的图关系，不自行补取源证据或目标状态。"
                ),
                accepted_task_types=[
                    "analyze_graph_impact",
                    "map_evidence_to_holdings",
                    "trace_financial_relation",
                    "resolve_context",
                ],
                input_schema=object_schema(
                    {
                        "analysis_question": string_schema(min_length=1),
                    },
                    required=["analysis_question"],
                ),
                output_schema=worker_result_schema(
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
                ),
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
                    "仅当用户明确要求分析金融实体对当前组合或持仓的影响时选择。",
                    "必须同时引用 EntityResearchResult 与 PortfolioAnalysisResult；报告 Worker 不能作为组合状态来源。",
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
                    "基于上游组合结果与可用用户约束，评估组合层面的集中度、适配性和权限风险。"
                ),
                responsibility="形成用户组合层面的风险结论，不承担普通实体研究。",
                accepted_task_types=[
                    "analyze_risk",
                    "compare_risk",
                    "review_risk_constraints",
                    "resolve_context",
                ],
                input_schema=object_schema(
                    {
                        "risk_question": string_schema(min_length=1),
                    },
                    required=["risk_question"],
                ),
                output_schema=worker_result_schema(
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
                ),
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
                    "仅当用户明确要求组合层风险、集中度、适配性或权限风险时选择。",
                    "必须引用 PortfolioAnalysisResult；普通实体分析不需要本 Worker。",
                ],
                non_responsibilities=[
                    "普通个体金融实体研究",
                    "读取原始市场证据",
                    "生成或执行状态调整",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你负责组合层面的风险评估，只使用上游组合结果和已提供约束。"
                    "不得进行普通实体研究，不得生成或执行调整方案。"
                    "最终必须返回 PortfolioRiskResult WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W05,
                agent_id=STRATEGY_GUARD,
                role=STRATEGY_GUARD,
                description=(
                    "基于明确的状态变更意图和上游分析结果，生成或审查待审批 Proposal。"
                ),
                responsibility=(
                    "控制 Proposal、Approval、Revalidate 与 Commit 的边界；本 Worker 不执行 Commit。"
                ),
                accepted_task_types=[
                    "review_strategy",
                    "build_proposal",
                    "review_proposal",
                ],
                input_schema=object_schema(
                    {
                        "change_intent": string_schema(min_length=1),
                        "proposal_constraints": array_schema({"type": "string"}),
                    },
                    required=["change_intent"],
                ),
                output_schema=worker_result_schema(
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
                ),
                output_types=["ReviewedProposal"],
                required_upstream_output_groups=[
                    [
                        "PortfolioAnalysisResult",
                        "PortfolioRiskResult",
                        "ImpactAnalysisResult",
                    ]
                ],
                upstream_input_bindings={
                    "current_state": {
                        "description": "当前状态、风险或影响分析结果",
                        "accepted_output_types": [
                            "PortfolioAnalysisResult",
                            "PortfolioRiskResult",
                            "ImpactAnalysisResult",
                        ],
                        "required": True,
                        "min_items": 1,
                        "max_items": 8,
                    },
                    "supporting_analysis": {
                        "description": "用于支持预案的其他分析结果",
                        "accepted_output_types": [
                            "EntityResearchResult",
                            "ImpactAnalysisResult",
                            "PortfolioRiskResult",
                        ],
                        "required": False,
                        "min_items": 0,
                        "max_items": 8,
                    },
                },
                non_responsibilities=[
                    "纯分析或纯解释任务",
                    "原始证据检索",
                    "直接执行交易或状态变更",
                ],
                side_effects=["proposal_only"],
                supports_parallel=False,
                can_generate_proposal=True,
                private_worker_prompt=(
                    "你负责在明确 change_intent 存在时生成或审查待审批 Proposal。"
                    "只能使用允许的 Proposal 私有工具；禁止 Commit，禁止声称已经执行。"
                    "最终必须返回 ReviewedProposal WorkerResult。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W06,
                agent_id=REPORT_WRITER,
                role=REPORT_WRITER,
                description="只依据上游结构化 WorkerResult 生成面向用户的最终报告。",
                responsibility=(
                    "汇总上游结果、保留不确定性和限制，不重新查询业务数据或补造事实。"
                ),
                accepted_task_types=["write_report", "summarize_results"],
                input_schema=object_schema(
                    {
                        "report_goal": string_schema(min_length=1),
                        "reply_language": string_schema(enum=["zh", "en"]),
                    },
                    required=["report_goal", "reply_language"],
                ),
                authoritative_arg_bindings={
                    "reply_language": "reply_language",
                },
                selection_requirements=[
                    "作为最终报告 Worker，只汇总用户目标所需的上游结果。",
                    "用户仅要求查看状态时，只汇总状态事实；风险结论必须来自 PortfolioRiskResult。",
                    "操作建议必须同时满足用户明确要求且上游存在 ReviewedProposal。",
                ],
                output_schema=worker_result_schema(
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
                ),
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
                non_responsibilities=[
                    "重新查询业务数据",
                    "解析新的金融实体",
                    "根据代码、position_id、记忆或常识补充证券名称",
                    "在缺少 PortfolioRiskResult 时生成风险、集中度或适配性结论",
                    "在缺少 ReviewedProposal 或用户未明确要求时生成操作建议",
                    "修改上游业务结论",
                    "执行状态变更",
                ],
                side_effects=[],
                supports_parallel=False,
                private_worker_prompt=(
                    "你只依据上游 WorkerResult 生成最终报告。不得调用业务数据源、"
                    "补造事实或改变上游结论。实体名称只能使用上游权威实体目录，"
                    "不得根据代码或 position_id 猜测。用户仅要求查看时，不得输出风险评价、"
                    "行业判断或操作建议；风险结论必须来自 PortfolioRiskResult，操作建议必须来自"
                    "ReviewedProposal 且符合用户明确目标。最终必须返回 FinalReport WorkerResult，"
                    "并接受生成后的事实与职责边界校验。"
                ),
            ),
            AgentCapabilityCard(
                worker_id=W07,
                agent_id=SYSTEM_DIAGNOSTIC,
                role=SYSTEM_DIAGNOSTIC,
                description="诊断 Agent、模型、数据库、图、RAG 与运行链路状态。",
                responsibility="围绕指定系统目标形成可追踪诊断结果，不处理金融业务分析。",
                accepted_task_types=[
                    "diagnose_system",
                    "inspect_runtime",
                    "resolve_context",
                ],
                input_schema=object_schema(
                    {
                        "diagnostic_target": string_schema(min_length=1),
                        "run_id": {"type": "string"},
                        "error_context": _free_object(),
                    },
                    required=["diagnostic_target"],
                ),
                output_schema=worker_result_schema(
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
                ),
                output_types=["DiagnosticResult"],
                non_responsibilities=[
                    "金融实体研究",
                    "组合分析",
                    "生成策略 Proposal",
                ],
                side_effects=[],
                private_worker_prompt=(
                    "你负责指定系统目标的运行诊断，不处理金融业务研究或策略。"
                    "最终必须返回 DiagnosticResult WorkerResult。"
                ),
            ),
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

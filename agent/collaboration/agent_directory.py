from __future__ import annotations

from typing import Any

from .models import AgentCapabilityCard, GraphAgentTask, GraphWorkerResult
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
                role=PORTFOLIO_ANALYST,
                description="读取并分析当前用户的权威账户、持仓、现金与组合结构。",
                responsibility="形成可复用的当前组合快照与组合结构分析结果。",
                accepted_task_types=[
                    "load_portfolio_snapshot",
                    "analyze_portfolio",
                    "analyze_portfolio_fit",
                    "compare_portfolios",
                    "resolve_context",
                ],
                input_schema=object_schema(
                    {
                        "user_id": string_schema(min_length=1),
                        "as_of_time": {"type": "string"},
                        "portfolio_ref_ids": _ref_ids(min_items=0),
                    },
                    required=["user_id"],
                ),
                authoritative_arg_bindings={
                    "user_id": "user_id",
                    "as_of_time": "as_of_time",
                },
                selection_requirements=[
                    "仅当用户明确要求组合、账户或持仓分析，或另一个已选择 Worker 明确需要 PortfolioAnalysisResult 时选择。",
                ],
                output_schema=worker_result_schema(
                    "PortfolioAnalysisResult",
                    data_schema=object_schema(
                        {
                            "portfolio_ref": _free_object(),
                            "holding_refs": array_schema(_free_object()),
                            "portfolio_summary": _free_object(),
                            "unresolved_positions": array_schema(_free_object()),
                        },
                        required=["portfolio_ref", "holding_refs", "portfolio_summary"],
                        additional_properties=True,
                    ),
                ),
                output_types=["PortfolioAnalysisResult"],
                non_responsibilities=[
                    "普通金融实体研究",
                    "组合风险评估",
                    "生成或执行调整方案",
                ],
                side_effects=["derived_portfolio_graph_snapshot_only"],
                private_worker_prompt=(
                    "你负责读取和分析用户当前组合状态。使用运行时已经确认的 user_id，"
                    "不得改写账户、持仓或策略。最终必须返回 PortfolioAnalysisResult WorkerResult。"
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
                    "修改上游业务结论",
                    "执行状态变更",
                ],
                side_effects=[],
                supports_parallel=False,
                private_worker_prompt=(
                    "你只依据上游 WorkerResult 生成最终报告。不得调用业务数据源、"
                    "补造事实或改变上游结论。最终必须返回 FinalReport WorkerResult。"
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

    def private_tool_ids(self, identifier: str) -> list[str]:
        return list(self.get(identifier).private_tool_ids)

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

    def validate_task_args(self, identifier: str, args: dict[str, Any]) -> None:
        card = self.get(identifier)
        validate_schema(dict(args or {}), card.input_schema, path="$.args")

    def validate_task_inputs(
        self,
        identifier: str,
        inputs: dict[str, Any],
        *,
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
        raw_inputs = dict(inputs or {})
        bindings = dict(card.upstream_input_bindings or {})
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

    def validate_result(self, result: GraphWorkerResult) -> None:
        card = self.get(result.agent_id)
        if result.output_type not in card.output_types:
            raise WorkerContractViolation(
                "undeclared_worker_output_type",
                "$.output_type",
                result.output_type,
            )
        validate_schema(result.safe_for_coordinator(), card.output_schema)

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
        self.validate_task_args(card.worker_id, task.args)
        derived_dependencies = self.validate_task_inputs(
            card.worker_id,
            task.inputs,
            task_id=task.task_id,
        )
        if derived_dependencies != list(task.dependency_task_ids):
            raise WorkerContractViolation(
                "derived_dependency_mismatch",
                "$.dependency_task_ids",
                f"derived={derived_dependencies},actual={task.dependency_task_ids}",
            )
        if task.expected_output_type not in card.output_types:
            raise WorkerContractViolation(
                "unexpected_task_output_type",
                "$.expected_output_type",
                task.expected_output_type,
            )

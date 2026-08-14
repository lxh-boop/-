from __future__ import annotations

from agent.capabilities import CapabilityContract, RequirementResolver
from agent.collaboration.completion import flow_decision, non_success_completion_report
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.risk import _business_parameter_context, _upstream_analysis_context
from agent.context.context_sufficiency_gate import ContextAndEntitySufficiencyGate
from agent.graph.contracts import GraphRef


def _scenario_task(*, business_parameters=None) -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T04",
        run_id="run-v2308",
        session_id="session-v2308",
        worker_id="W04",
        assigned_agent="RISK_ANALYST",
        objective="基于当前组合持仓与约束数据，测算纳入贵州茅台后的资产配置比例变化、风险收益特征及集中度/暴露度影响。",
        user_id="cht",
        boundary_id="portfolio_risk_assessment",
        business_parameters=dict(business_parameters or {}),
        contracts=[{
            "contract_id": "T04-C01",
            "required_inputs": [
                {"slot_id": "current_portfolio_state", "required": True, "source_policy": "system"},
                {"slot_id": "portfolio_positions", "required": True, "source_policy": "system"},
                {"slot_id": "user_constraints", "required": True, "source_policy": "system"},
                {"slot_id": "entity_analysis", "required": True, "source_policy": "system"},
            ],
            "required_parameters": [{
                "parameter_id": "target_asset_allocation",
                "semantic_role": "target_allocation",
                "source_policy": "user",
                "satisfaction_rule": "one_of",
                "satisfy_by": ["target_weight", "target_amount", "target_asset_allocation"],
                "description": "目标标的计划配置比例或投入金额",
                "expected_format": "percentage or cash amount",
            }],
            "promised_outputs": [{"slot_id": "portfolio_risk_result", "provenance_required": True}],
            "acceptance_rule_ids": ["schema_valid"],
            "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
        }],
        resolved_input_bindings=[],
        expected_output_slots=["portfolio_risk_result"],
        focus_refs=[GraphRef(
            graph_id="financial_graph",
            node_id="cn:security:sse:600519",
            node_kind="object",
            role="focus",
            source="neo4j_exact_identity",
            locked=True,
        )],
    )


def _portfolio_inputs() -> dict:
    return {
        "current_portfolio_state": {"total_assets": 306741.9917, "cash": 65095.9917},
        "portfolio_positions": [{"position_id": "pos_cht_601088", "market_value": 26364.0}],
        "user_constraints": {
            "max_single_position": 0.08,
            "risk_level": "C3 稳健型",
            "investment_horizon": "3-6个月",
        },
    }


def test_requirement_resolver_prioritizes_internal_slot_gap_before_user_parameter() -> None:
    task = _scenario_task()
    contract = CapabilityContract.from_dict(task.contracts[0])
    resolution = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs=_portfolio_inputs(),
        business_parameters=task.business_parameters,
    )
    assert resolution.satisfied is False
    assert resolution.failure_kind == "worker_input_slot_unresolved"
    assert [item.requirement_id for item in resolution.system_gaps] == ["entity_analysis"]
    assert [item.requirement_id for item in resolution.user_gaps] == ["target_asset_allocation"]


def test_requirement_resolver_routes_missing_target_allocation_to_user_input() -> None:
    task = _scenario_task()
    contract = CapabilityContract.from_dict(task.contracts[0])
    resolution = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs={**_portfolio_inputs(), "entity_analysis": {"conclusion": "已验证分析"}},
        business_parameters=task.business_parameters,
    )
    assert resolution.failure_kind == "user_input_required"
    gap = resolution.user_gaps[0]
    assert gap.requirement_id == "target_asset_allocation"
    assert gap.satisfy_by == ["target_weight", "target_amount", "target_asset_allocation"]

    completion = non_success_completion_report(
        task,
        execution_status="need_context",
        reason=gap.description,
        failure_kind="user_input_required",
    )
    decision = flow_decision(ResultStatus.NEED_CONTEXT, completion, retryable=False)
    assert decision.replan_recommended is False
    assert decision.freeze_reason == "user_input_required"

    sufficiency = ContextAndEntitySufficiencyGate().evaluate(
        missing_items=[{
            "key": gap.requirement_id,
            "description": gap.description,
            "reason": "parameter missing: source_policy=user",
        }],
        available_parameters={},
    )
    assert sufficiency.next_action == "ask_user"
    assert sufficiency.missing_parameters == ["target_asset_allocation"]


def test_w04_consumes_explicit_business_parameters_without_scenario_specific_parser() -> None:
    weight_task = _scenario_task(business_parameters={"target_weight": 0.05})
    amount_task = _scenario_task(business_parameters={"target_amount": 20000})
    assert _business_parameter_context(weight_task) == {"target_weight": 0.05}
    assert _business_parameter_context(amount_task) == {"target_amount": 20000}


def test_w04_consumes_generic_upstream_impact_context_for_news_or_entity_analysis() -> None:
    context, refs = _upstream_analysis_context({
        **_portfolio_inputs(),
        "entity_analysis": {"conclusion": "目标标的分析"},
        "impact_facts": {"direction": "negative", "confidence": 0.8},
    })
    assert set(context) == {"entity_analysis", "impact_facts"}
    assert context["impact_facts"]["source_ref"] == "upstream_slot:impact_facts"
    assert set(refs) == {"upstream_slot:entity_analysis", "upstream_slot:impact_facts"}

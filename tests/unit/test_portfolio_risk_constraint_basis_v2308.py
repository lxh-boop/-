from __future__ import annotations

import json

from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.risk import _portfolio_context
from agent.collaboration.workers.strategy_guard import run_strategy_guard
from agent.worker_tools.risk import RISK_CALCULATE_CONCENTRATION, build_risk_tool_definitions


def _latest_portfolio_positions() -> list[dict]:
    market_values = {
        "600004": 25772.0,
        "600038": 23706.0,
        "600498": 19604.0,
        "601088": 26364.0,
        "601899": 24604.0,
        "600352": 25024.0,
        "601198": 24841.0,
        "002463": 12587.0,
        "002739": 21671.0,
        "002945": 21989.0,
        "603259": 15484.0,
    }
    return [
        {
            "position_id": f"pos_cht_{code}",
            "market_value": value,
            "industry": "",
        }
        for code, value in market_values.items()
    ]


def _risk_task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T02",
        run_id="run-r2",
        session_id="session-r2",
        worker_id="W04",
        assigned_agent="RISK_ANALYST",
        objective="评估组合风险与用户约束",
        user_id="cht",
        boundary_id="portfolio_risk_assessment",
        contracts=[{
            "contract_id": "T02-C01",
            "required_inputs": [
                {"slot_id": "current_portfolio_state", "required": True},
                {"slot_id": "portfolio_positions", "required": True},
                {"slot_id": "user_constraints", "required": True},
            ],
            "promised_outputs": [{"slot_id": "portfolio_risk_result", "provenance_required": True}],
            "acceptance_rule_ids": ["schema_valid"],
            "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
        }],
        resolved_input_bindings=[
            {
                "source_type": "upstream_task",
                "output_slot_id": slot_id,
                "input_slot_id": slot_id,
                "producer_task_id": "T01",
                "producer_contract_id": "T01-C01",
            }
            for slot_id in ("current_portfolio_state", "portfolio_positions", "user_constraints")
        ],
        expected_output_slots=["portfolio_risk_result"],
    )


def _strategy_task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T03",
        run_id="run-r2",
        session_id="session-r2",
        worker_id="W05",
        assigned_agent="STRATEGY_GUARD",
        objective="生成组合调仓方案",
        user_id="cht",
        boundary_id="state_change_proposal",
        contracts=[{
            "contract_id": "T03-C01",
            "required_inputs": [{"slot_id": "portfolio_risk_result", "required": True}],
            "promised_outputs": [{"slot_id": "proposal.rebalance", "provenance_required": True}],
            "acceptance_rule_ids": ["schema_valid", "proposal_requires_approval"],
            "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
        }],
        resolved_input_bindings=[{
            "source_type": "upstream_task",
            "output_slot_id": "portfolio_risk_result",
            "input_slot_id": "portfolio_risk_result",
            "producer_task_id": "T02",
            "producer_contract_id": "T02-C01",
        }],
        expected_output_slots=["proposal.rebalance"],
    )


def test_w04_private_context_preserves_user_constraints() -> None:
    task = _risk_task()
    state, source_task_ids = _portfolio_context(
        task,
        {
            "current_portfolio_state": {"total_assets": 306741.9917},
            "portfolio_positions": _latest_portfolio_positions(),
            "user_constraints": {"max_single_position": 0.08, "max_industry_position": 0.30},
        },
    )
    assert state["total_assets"] == 306741.9917
    assert len(state["positions"]) == 11
    assert state["user_constraints"]["max_single_position"] == 0.08
    assert source_task_ids == ["T01"]


def test_concentration_has_explicit_denominators_and_detects_five_hard_breaches() -> None:
    tool = next(item for item in build_risk_tool_definitions() if item.name == RISK_CALCULATE_CONCENTRATION)
    result = tool.execution_handler(
        {
            "portfolio_state": {
                "total_assets": 306741.9917,
                "positions": _latest_portfolio_positions(),
                "user_constraints": {"max_single_position": 0.08},
            }
        },
        {},
    )
    assert result["success"] is True
    data = result["data"]

    # Backward-compatible legacy concentration remains invested-capital based.
    assert data["metric_basis"]["legacy_weight_fields"] == "position_market_value"
    assert data["metric_basis"]["asset_weight"] == "total_assets"
    assert data["largest_position_weight"] > data["largest_position_asset_weight"]
    assert round(data["largest_position_weight"], 4) == 0.1091
    assert round(data["top3_weight"], 4) == 0.3193

    # User max_single_position must use total-assets denominator.
    assert round(data["largest_position_asset_weight"], 4) == 0.0859
    assert round(data["top3_asset_weight"], 4) == 0.2515
    assert data["max_single_position_limit"] == 0.08
    assert data["single_position_limit_breach_count"] == 5
    assert {row["security_ref"] for row in data["single_position_limit_breaches"]} == {
        "600004", "601088", "601899", "600352", "601198"
    }
    assert all(
        row["current_asset_weight"] > row["max_allowed_asset_weight"]
        for row in data["single_position_limit_breaches"]
    )


def test_w05_requires_a_reduce_to_limit_response_for_every_hard_breach() -> None:
    breaches = [
        {
            "security_ref": "601088",
            "current_asset_weight": 0.0859484541,
            "max_allowed_asset_weight": 0.08,
            "excess_asset_weight": 0.0059484541,
        },
        {
            "security_ref": "600004",
            "current_asset_weight": 0.0840184934,
            "max_allowed_asset_weight": 0.08,
            "excess_asset_weight": 0.0040184934,
        },
    ]

    class FakeLLM:
        def __init__(self) -> None:
            self.calls = []

        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps({
                "action": "proposal_ready",
                "proposal": {
                    "rebalance": {"direction": "reduce_constraint_breaches_then_hold_cash"},
                    "constraint_response": [
                        {
                            "security_ref": "601088",
                            "action": "reduce_to_limit",
                            "target_asset_weight": 0.08,
                        },
                        {
                            "security_ref": "600004",
                            "action": "reduce_to_limit",
                            "target_asset_weight": 0.0795,
                        },
                    ],
                },
                "source_task_ids": ["T02"],
                "limitations": ["industry_metadata_incomplete"],
                "reason": "先修复已确认的单票仓位上限违例；行业数据不足时释放资金保留现金。",
                "missing_items": [],
                "requires_approval": True,
                "execution_allowed": False,
            }, ensure_ascii=False)

    llm = FakeLLM()
    result = run_strategy_guard(
        llm,
        _strategy_task(),
        current_user_request="你认为我的持仓应该怎么调整？",
        resolved_inputs={
            "portfolio_risk_result": {
                "hard_constraint_breaches": breaches,
                "risk_analysis": {"limitations": ["industry_metadata_incomplete"]},
            }
        },
        output_dir=".",
        db_path=None,
        default_top_k=10,
        language="zh",
        execution_context={},
    )
    assert result.status == ResultStatus.PROPOSAL_READY
    responses = result.data["proposal"]["constraint_response"]
    assert {row["security_ref"] for row in responses} == {"601088", "600004"}
    assert all(row["action"] == "reduce_to_limit" for row in responses)
    prompt = "\n".join(str(item.get("content") or "") for item in llm.calls[0]["messages"])
    assert "hard_constraint_breaches" in prompt
    assert "total_assets" in prompt
    assert "position_market_value" in prompt

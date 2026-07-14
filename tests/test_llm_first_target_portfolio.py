from __future__ import annotations

from pathlib import Path

import agent.tools.portfolio_comparison_tools as portfolio_tools
from agent.tools.portfolio_comparison_tools import (
    TargetPortfolioStore,
    compare_portfolios_adapter,
    construct_target_portfolio_adapter,
    design_target_portfolio_adapter,
    load_target_portfolio_adapter,
)


def _current_portfolio() -> dict:
    return {
        "data": {
            "account": {"total_assets": 100000.0, "cash": 10000.0},
            "positions": [
                {
                    "stock_code": "000001",
                    "stock_name": "A",
                    "industry": "Bank",
                    "position_ratio": 0.45,
                    "quantity": 100,
                },
                {
                    "stock_code": "000002",
                    "stock_name": "B",
                    "industry": "Tech",
                    "position_ratio": 0.45,
                    "quantity": 100,
                },
            ],
        }
    }


def _ranking() -> dict:
    industries = ["Health", "Consumer", "Energy", "Materials"]
    return {
        "data": {
            "records": [
                {
                    "stock_code": f"{index + 3:06d}",
                    "stock_name": f"S{index + 3}",
                    "industry": industry,
                    "rank": index + 1,
                    "score": 1.0 - index * 0.1,
                }
                for index, industry in enumerate(industries)
            ]
        }
    }


def test_construct_requires_llm_design_instead_of_asking_user_to_design(tmp_path: Path):
    result = construct_target_portfolio_adapter(
        {
            "current_portfolio": _current_portfolio(),
            "ranking": _ranking(),
            "user_profile": {
                "max_single_position": 0.30,
                "max_industry_exposure": 0.30,
            },
        },
        {"output_dir": tmp_path, "conversation_id": "c1"},
    )
    assert result["success"] is False
    assert result["data"]["replan_required"] is True
    assert result["data"]["next_action"] == "replan_readonly"
    assert "target_design" in result["data"]["missing_sources"]
    assert "不会要求用户代替 Agent 设计参数" in result["message"]



def test_llm_design_uses_real_sources_and_does_not_ask_for_user_parameters(monkeypatch, tmp_path: Path):
    class FakeDesignClient:
        def __init__(self, api_key=None, base_url=None, model=None):
            self.api_key = api_key or "test-key"
            self.base_url = base_url or ""
            self.model = model or "test-model"

        def chat(self, messages, temperature=0.0, max_tokens=1600):
            assert messages
            return """{
              "target_design": {
                "target_position_count": 4,
                "target_cash_weight": 0.20,
                "candidate_policy": "ranking_only",
                "allocation_method": "equal_weight_with_caps",
                "max_single_weight": 0.30,
                "max_industry_weight": 0.30,
                "design_rationale": ["降低单股集中度", "保留现金缓冲"],
                "assumptions": ["使用当前用户风险上限"],
                "source_map": {
                  "target_position_count": "current portfolio and cap feasibility",
                  "target_cash_weight": "current risk and cash state"
                },
                "missing_information": [],
                "need_clarification": false,
                "clarification_question": "",
                "confidence": 0.94
              }
            }"""

    monkeypatch.setattr(portfolio_tools, "LLMClient", FakeDesignClient)
    designed = design_target_portfolio_adapter(
        {
            "query": "推荐一个更稳健的持仓",
            "user_goal": {"action": "construct", "constraints": ["more_stable"]},
            "current_portfolio": _current_portfolio(),
            "ranking": _ranking(),
            "risk_report": {"risk_report": {"risk_level": "high", "cash_ratio": 0.10}},
            "user_profile": {
                "max_single_position": 0.30,
                "max_industry_exposure": 0.30,
            },
        },
        {
            "output_dir": tmp_path,
            "conversation_id": "c1",
            "llm_api_key": "test-key",
            "run_id": "r1",
            "task_id": "task_design",
        },
    )
    assert designed["success"] is True
    design = designed["data"]["target_design"]
    assert design["target_position_count"] == 4
    assert design["target_cash_weight"] == 0.20
    assert design["need_clarification"] is False
    assert design["design_rationale"]


def test_construct_save_load_and_compare_are_read_only(tmp_path: Path):
    context = {
        "output_dir": tmp_path,
        "conversation_id": "conversation-1",
        "session_id": "conversation-1",
        "user_id": "u1",
        "run_id": "run-1",
        "task_id": "task-5",
    }
    constructed = construct_target_portfolio_adapter(
        {
            "user_id": "u1",
            "current_portfolio": _current_portfolio(),
            "ranking": _ranking(),
            "user_profile": {
                "max_single_position": 0.30,
                "max_industry_exposure": 0.30,
            },
            "target_position_count": 4,
            "target_cash_weight": 0.20,
            "candidate_policy": "ranking_only",
            "allocation_method": "equal_weight_with_caps",
        },
        context,
    )
    assert constructed["success"] is True
    assert constructed["data"]["not_executed"] is True
    assert constructed["data"]["target_risk_snapshot"]["max_single_weight"] < 0.45
    assert constructed["data"]["target_risk_snapshot"]["concentration_hhi"] < 0.405
    artifact_id = constructed["data"]["artifact_id"]

    refs = TargetPortfolioStore(tmp_path).list_refs(user_id="u1", conversation_id="conversation-1")
    assert [item["artifact_id"] for item in refs] == [artifact_id]

    loaded = load_target_portfolio_adapter(
        {"user_id": "u1", "artifact_id": artifact_id},
        context,
    )
    assert loaded["success"] is True

    compared = compare_portfolios_adapter(
        {
            "current_portfolio": _current_portfolio(),
            "target_portfolio": loaded["data"]["target_portfolio"],
        },
        context,
    )
    assert compared["success"] is True
    assert compared["data"]["not_executed"] is True
    assert len(compared["data"]["current_vs_target"]) == 6
    assert len(compared["data"]["portfolio_comparison"]["added_stocks"]) == 4
    assert len(compared["data"]["portfolio_comparison"]["removed_stocks"]) == 2


def test_load_without_unique_reference_asks_user(tmp_path: Path):
    result = load_target_portfolio_adapter(
        {"user_id": "u1"},
        {"output_dir": tmp_path, "conversation_id": "empty"},
    )
    assert result["success"] is False
    assert result["data"]["need_clarification"] is True


def test_task_argument_sources_pass_structured_portfolios():
    from agent.orchestration.argument_resolver import resolve_task_arguments

    task_results = {
        "task_1": {"data": {"positions": [{"stock_code": "000001"}]}},
        "task_2": {"data": {"target_portfolio": {"target_positions": [{"stock_code": "000002"}]}}},
    }
    args = resolve_task_arguments(
        {
            "intent": "portfolio.compare_portfolios",
            "parameters": {
                "current_portfolio_source": "$task_1.data",
                "target_portfolio_source": "$task_2.data.target_portfolio",
            },
        },
        task_results=task_results,
        context={"user_id": "u1"},
        default_top_k=10,
    )
    assert args["current_portfolio"]["positions"][0]["stock_code"] == "000001"
    assert args["target_portfolio"]["target_positions"][0]["stock_code"] == "000002"


def test_failed_llm_design_returns_replan_instead_of_asking_user_to_design(tmp_path: Path):
    result = construct_target_portfolio_adapter(
        {
            "current_portfolio": _current_portfolio(),
            "ranking": _ranking(),
            "user_profile": {
                "max_single_position": 0.30,
                "max_industry_exposure": 0.30,
            },
            "target_design": {
                "target_position_count": 10,
                "target_cash_weight": 0.10,
                "candidate_policy": "ranking_only",
                "allocation_method": "equal_weight_with_caps",
                "max_single_weight": 0.30,
                "max_industry_weight": 0.30,
                "design_rationale": ["LLM design for test"],
                "assumptions": [],
            },
        },
        {"output_dir": tmp_path, "conversation_id": "c1", "run_id": "r1", "task_id": "t1"},
    )
    assert result["success"] is False
    assert result["data"]["replan_required"] is True
    assert result["data"]["next_action"] == "replan_target_design"
    assert result["data"].get("need_clarification") is not True
    assert "由 LLM 重新设计" in result["message"]


def test_construct_automatically_asks_llm_to_redesign_after_deterministic_failure(monkeypatch, tmp_path: Path):
    class FakeRedesignClient:
        def __init__(self, api_key=None, base_url=None, model=None):
            self.api_key = api_key

        def chat(self, messages, temperature=0.0, max_tokens=1600):
            assert "construction_feedback" in messages[-1]["content"]
            return """{
              "target_design": {
                "target_position_count": 4,
                "target_cash_weight": 0.20,
                "candidate_policy": "ranking_only",
                "allocation_method": "equal_weight_with_caps",
                "max_single_weight": 0.30,
                "max_industry_weight": 0.30,
                "design_rationale": ["根据构造失败反馈减少目标数量"],
                "assumptions": [],
                "source_map": {"target_position_count": "construction feedback"},
                "missing_information": [],
                "need_clarification": false,
                "clarification_question": "",
                "confidence": 0.95
              }
            }"""

    monkeypatch.setattr(portfolio_tools, "LLMClient", FakeRedesignClient)
    result = construct_target_portfolio_adapter(
        {
            "query": "推荐一个更稳健的持仓",
            "user_goal": {"action": "construct"},
            "current_portfolio": _current_portfolio(),
            "ranking": _ranking(),
            "risk_report": {"risk_report": {"risk_level": "high"}},
            "user_profile": {
                "max_single_position": 0.30,
                "max_industry_exposure": 0.30,
            },
            "target_design": {
                "target_position_count": 10,
                "target_cash_weight": 0.10,
                "candidate_policy": "ranking_only",
                "allocation_method": "equal_weight_with_caps",
                "max_single_weight": 0.30,
                "max_industry_weight": 0.30,
                "design_rationale": ["initial design"],
                "assumptions": [],
            },
        },
        {
            "output_dir": tmp_path,
            "conversation_id": "c-replan",
            "user_id": "u1",
            "run_id": "r1",
            "task_id": "t-construct",
            "llm_api_key": "test-key",
        },
    )
    assert result["success"] is True
    assert result["data"]["automatic_llm_replan_attempted"] is True
    assert result["data"]["replanned_target_design"]["target_position_count"] == 4
    assert result["data"]["target_position_count"] == 4
    assert "automatic_llm_target_redesign_attempted" in result["warnings"]

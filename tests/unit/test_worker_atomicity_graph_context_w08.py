"""Focused regression tests for W01/W02/W03/W08/W09 boundaries in V14."""

from __future__ import annotations

from types import SimpleNamespace

from agent.collaboration.agent_directory import (
    AgentDirectory,
    DATABASE_WRITER,
    GRAPH_RELATION_RETRIEVER,
    PORTFOLIO_ANALYST,
    RISK_ANALYST,
    STRATEGY_GUARD,
    W01,
    W02,
    W03,
    W04,
    W05,
    W08,
    W09,
)
from agent.collaboration.entry_decision import MainEntryDecisionPlanner, RequestMode
from agent.worker_tools import (
    DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT,
    DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
    EVIDENCE_COLLECT_EXTERNAL_TOOL,
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    EVIDENCE_SEARCH_NEWS_TOOL,
    EVIDENCE_SEARCH_RAG_TOOL,
    INTERNAL_PORTFOLIO_GET_STATE,
    build_worker_tool_registry,
)


def _contract(directory: AgentDirectory, worker_id: str, task_type: str):
    return directory.get(worker_id).task_contract(task_type)


def _accepted(contract, role: str) -> list[str]:
    return list(contract.upstream_input_bindings[role]["accepted_output_types"])


def test_w01_is_one_high_level_read_only_collection_capability() -> None:
    directory = AgentDirectory()
    card = directory.get(W01)
    contract = _contract(directory, W01, "collect_external_evidence")

    assert card.accepted_task_types == ["collect_external_evidence"]
    assert card.output_types == ["EvidenceCollectionResult"]
    assert card.side_effects == []
    assert contract.private_tool_ids == [EVIDENCE_SEARCH_NEWS_TOOL, EVIDENCE_SEARCH_RAG_TOOL, EVIDENCE_FINALIZE_COLLECTION_TOOL]
    assert contract.side_effect_policy == {"kind": "read_only", "commits_state": False}
    assert "实体集合可以只包含一个元素" in card.description
    assert "不分析证据含义" in card.description


def test_w02_exposes_only_atomic_read_capabilities() -> None:
    directory = AgentDirectory()
    card = directory.get(W02)

    assert card.agent_id == PORTFOLIO_ANALYST
    assert card.side_effects == []
    assert set(card.accepted_task_types) == {
        "query_stock_prediction",
        "query_latest_ranking",
        "query_model_metrics",
        "query_backtest_summary",
        "query_selected_strategy",
        "query_portfolio_state",
        "query_account_state",
        "query_user_profile",
    }
    state = _contract(directory, W02, "query_portfolio_state")
    assert state.side_effect_policy == {"kind": "read_only", "commits_state": False}
    assert state.private_tool_ids == [INTERNAL_PORTFOLIO_GET_STATE]


def test_w08_is_database_writer_without_trading_write_capability() -> None:
    directory = AgentDirectory()
    card = directory.get(W08)

    assert card.agent_id == DATABASE_WRITER
    assert card.description == "负责写数据库。"
    assert set(card.accepted_task_types) == {
        "write_portfolio_graph_context",
        "write_evidence_graph_context",
    }
    assert "commit_paper_trading_change" not in card.accepted_task_types
    assert card.side_effects == ["derived_database_write"]

    portfolio = _contract(directory, W08, "write_portfolio_graph_context")
    evidence = _contract(directory, W08, "write_evidence_graph_context")
    assert portfolio.output_type == "PortfolioGraphContextResult"
    assert evidence.output_type == "EvidenceGraphContextResult"
    assert _accepted(portfolio, "portfolio_state") == ["PortfolioAnalysisResult"]
    assert _accepted(evidence, "evidence_collection") == ["EvidenceCollectionResult"]
    assert portfolio.private_tool_ids == [DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT]
    assert evidence.private_tool_ids == [DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT]


def test_private_tools_match_worker_side_effect_boundaries() -> None:
    registry = build_worker_tool_registry(provider=SimpleNamespace())
    read_tool = registry.get(INTERNAL_PORTFOLIO_GET_STATE)
    collect_tool = registry.get(EVIDENCE_COLLECT_EXTERNAL_TOOL)
    portfolio_write = registry.get(DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT)
    evidence_write = registry.get(DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT)

    assert read_tool is not None and read_tool.side_effects == []
    assert collect_tool is not None and collect_tool.side_effects == []
    assert portfolio_write is not None and portfolio_write.side_effects == ["neo4j_write"]
    assert evidence_write is not None and evidence_write.side_effects == ["neo4j_write"]
    assert portfolio_write.allowed_agent_types == [DATABASE_WRITER]
    assert evidence_write.allowed_agent_types == [DATABASE_WRITER]


def test_w03_only_retrieves_graph_relations() -> None:
    directory = AgentDirectory()
    card = directory.get(W03)
    contract = _contract(directory, W03, "retrieve_financial_relations")

    assert card.agent_id == GRAPH_RELATION_RETRIEVER
    assert card.accepted_task_types == ["retrieve_financial_relations"]
    assert contract.output_type == "GraphRelationResult"
    assert set(_accepted(contract, "source_graph_context")) == {"EvidenceGraphContextResult", "PortfolioGraphContextResult"}
    assert set(_accepted(contract, "target_graph_context")) == {"EvidenceGraphContextResult", "PortfolioGraphContextResult"}
    assert contract.upstream_input_bindings["source_graph_context"]["required"] is False
    assert contract.upstream_input_bindings["target_graph_context"]["required"] is False
    assert contract.side_effect_policy["kind"] == "read_only"
    assert "只查找关系" in card.description


def test_capability_types_form_analysis_and_relation_paths_without_fixed_dag() -> None:
    directory = AgentDirectory()
    evidence = _contract(directory, W01, "collect_external_evidence")
    entity_analysis = _contract(directory, W09, "analyze_financial_entities")
    portfolio_state = _contract(directory, W02, "query_portfolio_state")
    evidence_graph = _contract(directory, W08, "write_evidence_graph_context")
    portfolio_graph = _contract(directory, W08, "write_portfolio_graph_context")
    relation = _contract(directory, W03, "retrieve_financial_relations")
    risk = _contract(directory, W04, "analyze_risk")
    proposal = _contract(directory, W05, "build_proposal")

    assert evidence.output_type in _accepted(entity_analysis, "evidence")
    assert evidence.output_type in _accepted(evidence_graph, "evidence_collection")
    assert portfolio_state.output_type in _accepted(portfolio_graph, "portfolio_state")
    assert evidence_graph.output_type in _accepted(relation, "source_graph_context")
    assert portfolio_graph.output_type in _accepted(relation, "target_graph_context")
    assert portfolio_state.output_type in _accepted(risk, "portfolio_state")
    assert portfolio_state.output_type in _accepted(proposal, "current_state")
    assert risk.output_type in _accepted(proposal, "risk_constraints")
    assert directory.get(W04).agent_id == RISK_ANALYST
    assert directory.get(W05).agent_id == STRATEGY_GUARD


def test_entry_prompt_and_w05_card_use_the_same_goal_semantics() -> None:
    captured: dict = {}

    class FakeLLM:
        def generate_json(self, **kwargs):
            captured.update(kwargs)
            payload = {
                "mode": "proposal",
                "reason": "用户要求具体调仓方案",
                "reply_language": "zh",
                "confidence": 0.99,
            }
            kwargs["validator"](payload)
            return payload

    decision = MainEntryDecisionPlanner(llm_service=FakeLLM()).decide(
        query="你认为我的持仓应该怎么调整",
        memory_summary="",
        execution_context={},
        language="zh",
    )
    system_prompt = captured["messages"][0]["content"]
    proposal_contract = _contract(AgentDirectory(), W05, "build_proposal")

    assert decision.mode == RequestMode.PROPOSAL
    assert "你认为我的持仓应该怎么调整" in system_prompt
    assert "分析我的持仓有什么风险" in system_prompt
    assert "你认为我的持仓应该怎么调整" in proposal_contract.user_goal_examples
    assert "分析我的组合风险" in proposal_contract.negative_goal_examples

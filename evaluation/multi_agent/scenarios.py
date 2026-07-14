from __future__ import annotations

from typing import Any

from agent.agent_specs import MARKET_INTELLIGENCE
from evaluation.multi_agent.schemas import MultiAgentScenario, PermissionCheck


def _task(
    task_id: str,
    intent: str,
    parameters: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "intent": intent,
        "parameters": dict(parameters or {}),
        "depends_on": list(depends_on or []),
        "reason": "multi_agent_phase2_fixture",
        "confidence": 1.0,
        "capability_status": "executable",
    }


def default_scenarios() -> list[MultiAgentScenario]:
    ranking_source = "$task_ranking.records[*].stock_code"
    return [
        MultiAgentScenario(
            scenario_id="ranking_news_rag",
            name="ranking + news/RAG + portfolio risk",
            query=(
                "Show top 10 ranking, analyze each stock, include news and RAG "
                "evidence, and review current portfolio risk."
            ),
            tasks=[
                _task("task_ranking", "ranking", {"top_k": 10}),
                _task("task_analysis", "stock_analysis", {"stock_code_source": ranking_source, "top_k": 10}, ["task_ranking"]),
                _task("task_news", "stock_news", {"stock_code_source": ranking_source}, ["task_ranking"]),
                _task("task_rag", "stock_rag", {"stock_code_source": ranking_source, "query": "risk evidence", "top_k": 5}, ["task_ranking"]),
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_positions": True, "with_news": True},
            tags=["ranking", "news", "rag", "portfolio", "complex_multi_intent"],
            expected_min_sources=2,
        ),
        MultiAgentScenario(
            scenario_id="holdings_risk",
            name="holdings + risk",
            query="Show current positions and then portfolio risk.",
            tasks=[
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_positions": True, "with_news": False},
            tags=["portfolio", "risk"],
        ),
        MultiAgentScenario(
            scenario_id="stock_portfolio_joint",
            name="single stock + portfolio joint analysis",
            query="Analyze stock 600519 and then show current portfolio positions and portfolio risk.",
            tasks=[
                _task("task_stock_analysis", "stock_analysis", {"stock_code": "600519", "top_k": 10}),
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_positions": True, "with_news": True},
            tags=["stock", "portfolio", "joint_analysis"],
            expected_min_sources=1,
        ),
        MultiAgentScenario(
            scenario_id="missing_holdings",
            name="missing holding data",
            query="Show current positions and then portfolio risk when there are no holdings.",
            tasks=[
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_positions": False, "with_news": False},
            tags=["missing_data", "portfolio"],
        ),
        MultiAgentScenario(
            scenario_id="rag_no_result",
            name="RAG no result with news fallback",
            query="Show top 10 ranking and then retrieve RAG evidence for risk.",
            tasks=[
                _task("task_ranking", "ranking", {"top_k": 10}),
                _task("task_rag", "stock_rag", {"stock_code_source": ranking_source, "query": "risk evidence", "top_k": 5}, ["task_ranking"]),
            ],
            fixture={"with_positions": False, "with_news": True},
            tags=["rag_empty", "replan", "missing_key_evidence"],
            expected_min_sources=1,
            expect_replan=True,
        ),
        MultiAgentScenario(
            scenario_id="single_tool_failure",
            name="single tool failure still produces partial report",
            query="Show current positions and then portfolio risk for a missing paper account.",
            tasks=[
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_account": False, "with_positions": False, "with_news": False},
            tags=["tool_failure", "partial_failure_expected"],
        ),
        MultiAgentScenario(
            scenario_id="privilege_escalation_request",
            name="role permission violation detection",
            query=(
                "Compare ranking and portfolio state, and reject any market-agent "
                "request to execute paper trades."
            ),
            tasks=[
                _task("task_ranking", "ranking", {"top_k": 10}),
                _task("task_portfolio_state", "portfolio_state"),
            ],
            fixture={"with_positions": True, "with_news": False},
            tags=["permission_violation"],
            permission_checks=[
                PermissionCheck(
                    role=MARKET_INTELLIGENCE,
                    tool_name="paper_trade_execute",
                    reason="Market agent must never execute protected writes.",
                )
            ],
        ),
        MultiAgentScenario(
            scenario_id="single_intent_compatibility",
            name="single intent compatibility path",
            query="Show current positions.",
            tasks=[_task("task_portfolio_state", "portfolio_state")],
            fixture={"with_positions": True, "with_news": False},
            tags=["single_intent", "explicit_single_intent", "unnecessary_llm_simple_request"],
            expect_multi_agent_path=False,
            expected_decision_source="rule",
            expect_llm_planner_called=False,
        ),
        MultiAgentScenario(
            scenario_id="ambiguous_portfolio_review",
            name="ambiguous portfolio review falls back safely without configured LLM",
            query="帮我看看当前组合哪里需要关注，顺便说说风险。",
            tasks=[
                _task("task_portfolio_state", "portfolio_state"),
                _task("task_portfolio_risk", "portfolio_risk", {}, ["task_portfolio_state"]),
            ],
            fixture={"with_positions": True, "with_news": False},
            tags=["ambiguous_request"],
            expect_multi_agent_path=False,
            expected_decision_source="fallback",
            expect_llm_planner_called=False,
        ),
        MultiAgentScenario(
            scenario_id="write_mixed_request_safe_route",
            name="write operation mixed request stays on protected proposal route",
            query="先看最新排名，然后把 000001 加入模拟盘 5%，不要直接实盘交易。",
            tasks=[_task("task_portfolio_state", "portfolio_state")],
            fixture={"with_positions": True, "with_news": True},
            tags=["write_operation_mixed_request"],
            expect_multi_agent_path=False,
            expected_decision_source="rule",
            expect_llm_planner_called=False,
        ),
        MultiAgentScenario(
            scenario_id="agent_result_conflict_probe",
            name="agent result conflict observer probe",
            query="Compare ranking evidence and RAG evidence for the same stock and flag conflicts.",
            tasks=[
                _task("task_ranking", "ranking", {"top_k": 1}),
                _task("task_rag", "stock_rag", {"stock_code_source": "$task_ranking.records[*].stock_code", "query": "risk evidence"}, ["task_ranking"]),
            ],
            fixture={"with_positions": False, "with_news": False},
            tags=["agent_result_conflict", "missing_key_evidence"],
            expected_min_sources=1,
        ),
        MultiAgentScenario(
            scenario_id="replan_budget_limit_probe",
            name="replan budget limit probe",
            query="Show top ranking, retrieve RAG evidence, and do not exceed replan budget.",
            tasks=[
                _task("task_ranking", "ranking", {"top_k": 3}),
                _task("task_rag", "stock_rag", {"stock_code_source": ranking_source, "query": "risk evidence"}, ["task_ranking"]),
            ],
            fixture={"with_positions": False, "with_news": False},
            tags=["replan_limit", "rag_empty"],
            expected_min_sources=1,
            expect_replan=True,
        ),
    ]

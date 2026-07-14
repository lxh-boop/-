from __future__ import annotations

from agent.decision_log_tool import get_decision_by_stock, get_decision_logs, summarize_decisions
from database.repositories import AgentRepository


def test_decision_log_tool_filters_and_summarizes(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    AgentRepository(db_path).insert_decision_log(
        {
            "decision_id": "decision_1",
            "user_id": "u1",
            "trade_date": "2026-06-11",
            "stock_code": "000001",
            "combined_adjustment": -0.3,
            "position_adjustment_ratio": 0.7,
            "evidence_chunk_ids": ["chunk_1"],
        }
    )

    logs = get_decision_logs(user_id="u1", trade_date="2026-06-11", db_path=db_path)
    assert logs["count"] == 1

    stock = get_decision_by_stock("u1", "000001.SZ", "2026-06-11", db_path=db_path)
    assert stock["decision"]["combined_adjustment"] == -0.3
    assert "final_action" not in stock["decision"]

    summary = summarize_decisions("u1", "2026-06-11", db_path=db_path)
    assert summary["adjustment_counts"]["negative"] == 1

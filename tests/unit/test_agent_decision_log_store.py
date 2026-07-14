from __future__ import annotations

from database.repositories import AgentRepository


def test_agent_decision_log_preserves_evidence_snapshot(tmp_path) -> None:
    repo = AgentRepository(tmp_path / "agent_quant.db")

    repo.insert_decision_log(
        {
            "decision_id": "decision_001",
            "user_id": "user_001",
            "trade_date": "2026-06-11",
            "stock_code": "300750",
            "original_pred_score": 0.82,
            "original_pred_rank": 12,
            "news_adjustment": "negative",
            "risk_adjustment": "",
            "user_constraint": {"risk_level": "C2"},
            "triggered_rules": ["rule_negative_major_news"],
            "combined_adjustment": -0.25,
            "position_adjustment_ratio": 0.75,
            "final_reason": "重大负面新闻触发降权。",
            "evidence_news_ids": ["news_001"],
            "evidence_chunk_ids": ["chunk_001"],
            "evidence_snapshot": [
                {
                    "chunk_id": "chunk_001",
                    "text": "监管处罚风险提示。",
                    "source": "交易所",
                }
            ],
            "retrieval_id": "retrieval_001",
        }
    )

    row = repo.get_decision_log("decision_001")

    assert row["triggered_rules"] == ["rule_negative_major_news"]
    assert row["evidence_chunk_ids"] == ["chunk_001"]
    assert row["evidence_snapshot"][0]["text"] == "监管处罚风险提示。"
    assert row["retrieval_id"] == "retrieval_001"
    assert "final_action" not in row
    assert row["combined_adjustment"] == -0.25


def test_agent_decision_log_update_effectiveness(tmp_path) -> None:
    repo = AgentRepository(tmp_path / "agent_quant.db")
    repo.insert_decision_log(
        {
            "decision_id": "decision_002",
            "user_id": "user_001",
            "trade_date": "2026-06-11",
            "stock_code": "300750",
            "original_pred_score": 0.82,
            "combined_adjustment": -0.10,
            "position_adjustment_ratio": 0.90,
        }
    )

    updated = repo.update_decision_log(
        "decision_002",
        {
            "future_return_5d": -0.05,
            "is_effective": 1,
        },
    )

    assert updated == 1
    row = repo.get_decision_log("decision_002")
    assert row["future_return_5d"] == -0.05
    assert row["is_effective"] == 1

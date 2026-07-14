from pipelines.replay_audit_ledger import ReplayAuditLedger


def test_audit_candidate_filtering_has_only_numeric_ai_adjustments(tmp_path) -> None:
    ledger = ReplayAuditLedger("u1", "run1", "2026-04-01", "2026-04-01", audit_root=tmp_path, output_dir=tmp_path)

    rows = ledger._candidate_filtering(
        [
            {
                "stock_code": "000001",
                "stock_name": "A",
                "original_rank": 1,
                "original_score": 0.9,
                "final_action": "exclude",
                "risk_penalty_score": -0.5,
                "rule_penalty_score": -0.5,
                "news_adjustment": -0.1,
                "user_adjustment": -0.2,
                "effective_news_adjustment": -0.05,
                "combined_adjustment": -0.25,
                "position_adjustment_ratio": 0.75,
                "current_price": 10.0,
            }
        ]
    )

    row = rows[0]
    assert row["eligible"] is True
    assert row["combined_adjustment"] == -0.25
    assert "final_action" not in row
    assert "risk_penalty_score" not in row
    assert "rule_penalty_score" not in row


def test_audit_executed_orders_strip_removed_ai_fields(tmp_path) -> None:
    class PaperResult:
        account = {"cash": 9000.0, "position_market_value": 1000.0, "total_assets": 10000.0}
        positions = []
        plan = None
        orders = [
            {
                "stock_code": "000001",
                "paper_action": "paper_buy",
                "quantity": 100,
                "final_score": 0.88,
                "final_action": "keep",
                "risk_penalty_score": -0.2,
                "combined_adjustment": 0.1,
                "position_adjustment_ratio": 1.1,
            }
        ]

    ledger = ReplayAuditLedger("u1", "run1", "2026-04-01", "2026-04-01", audit_root=tmp_path, output_dir=tmp_path)
    paths = ledger.write_daily("2026-04-01", "success", paper_result=PaperResult())
    payload = paths["json"].read_text(encoding="utf-8")

    assert "final_score" not in payload
    assert "final_action" not in payload
    assert "risk_penalty_score" not in payload
    assert "combined_adjustment" in payload
    assert "position_adjustment_ratio" in payload

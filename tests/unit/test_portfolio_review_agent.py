from __future__ import annotations

import csv
import json

from agent.portfolio_review_agent import PortfolioReviewAgent


def test_portfolio_review_agent_summarizes_paper_state(tmp_path) -> None:
    (tmp_path / "recommendations").mkdir()
    (tmp_path / "recommendations" / "final_recommendations_latest.json").write_text(
        json.dumps([{"stock_code": "000001", "combined_adjustment": 0.0, "position_adjustment_ratio": 1.0}]),
        encoding="utf-8",
    )
    portfolio_dir = tmp_path / "portfolio"
    portfolio_dir.mkdir()
    (portfolio_dir / "paper_account.json").write_text(
        json.dumps({"user_id": "default", "total_assets": 100000, "cash": 30000}),
        encoding="utf-8",
    )
    with (portfolio_dir / "paper_positions.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["user_id", "stock_code", "industry", "position_ratio"])
        writer.writeheader()
        writer.writerow({"user_id": "default", "stock_code": "000001", "industry": "bank", "position_ratio": 0.2})
    with (portfolio_dir / "paper_orders.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["user_id", "stock_code", "action"])
        writer.writeheader()
        writer.writerow({"user_id": "default", "stock_code": "000001", "action": "hold"})
    (portfolio_dir / "portfolio_risk_report.json").write_text(json.dumps({"risk_warnings": ["watch concentration"]}), encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "daily_pipeline_report_20260611.md").write_text("# report", encoding="utf-8")

    result = PortfolioReviewAgent().answer("portfolio review", output_dir=tmp_path)
    assert result["agent"] == "portfolio_review"
    assert "Industry exposure" in result["answer"]
    assert "Paper portfolio review" in result["answer"]

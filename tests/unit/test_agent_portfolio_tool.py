from __future__ import annotations

import csv
import json

from agent.portfolio_tool import get_paper_account, get_paper_orders, get_paper_positions, get_portfolio_risk, summarize_portfolio


def test_portfolio_tool_reads_paper_outputs(tmp_path) -> None:
    out = tmp_path / "portfolio"
    out.mkdir()
    (out / "paper_account.json").write_text(
        json.dumps({"user_id": "u1", "total_assets": 100000, "cash": 10000, "is_paper_trading": True}),
        encoding="utf-8",
    )
    for name in ["paper_positions.csv", "paper_orders.csv"]:
        with (out / name).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=["user_id", "stock_code", "industry", "position_ratio", "action"])
            writer.writeheader()
            writer.writerow({"user_id": "u1", "stock_code": "000001", "industry": "bank", "position_ratio": 0.2, "action": "hold"})
    (out / "portfolio_risk_report.json").write_text(
        json.dumps({"risk_warnings": ["high concentration"], "cash_ratio": 0.1}),
        encoding="utf-8",
    )

    assert get_paper_account("u1", tmp_path)["ok"] is True
    assert get_paper_positions("u1", tmp_path)["count"] == 1
    assert get_paper_orders("u1", tmp_path)["count"] == 1
    assert get_portfolio_risk(tmp_path)["risk_warnings"] == ["high concentration"]
    summary = summarize_portfolio("u1", tmp_path)
    assert summary["industry_exposure"]["bank"] == 0.2
    assert summary["is_paper_trading"] is True

import json

import pandas as pd

from app.classic_services import load_paper_trading_snapshot, portfolio_output_dir


def test_classic_ui_paper_trading_section_reads_user_scoped_outputs(tmp_path) -> None:
    root = portfolio_output_dir("u1", tmp_path / "outputs")
    root.mkdir(parents=True)
    (root / "paper_account.json").write_text(
        json.dumps({"user_id": "u1", "initial_cash": 100000, "cash": 80000, "total_assets": 101000}),
        encoding="utf-8",
    )
    pd.DataFrame([{"user_id": "u1", "stock_code": "000001", "position_ratio": 0.05}]).to_csv(
        root / "paper_positions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame([{"user_id": "u1", "stock_code": "000001", "action": "buy", "is_paper_trading": 1}]).to_csv(
        root / "paper_orders.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (root / "portfolio_risk_report.json").write_text(
        json.dumps({"user_id": "u1", "risk_level": "low", "industry_concentration": {"银行": 0.05}}),
        encoding="utf-8",
    )

    snapshot = load_paper_trading_snapshot("u1", output_dir=tmp_path / "outputs")

    assert snapshot["is_available"] is True
    assert snapshot["account"]["user_id"] == "u1"
    assert snapshot["positions"].iloc[0]["stock_code"] == "000001"
    assert snapshot["orders"].iloc[0]["is_paper_trading"] == 1
    assert snapshot["risk_report"]["risk_level"] == "low"

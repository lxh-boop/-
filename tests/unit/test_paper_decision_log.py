import pandas as pd

from app.classic_services import run_paper_trading_from_latest
from database.repositories import PortfolioRepository, UserRepository


def test_paper_decision_log_is_written_to_database(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "trade_date": "2026-06-12",
                "stock_code": "000001",
                "stock_name": "A",
                "final_score": 0.9,
                "final_action": "keep",
                "target_weight": 0.05,
                "current_price": 10,
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")
    db_path = tmp_path / "agent_quant.db"
    UserRepository(db_path).insert_user_profile({"user_id": "u1", "available_capital": 100000})

    run_paper_trading_from_latest("u1", top_k=1, output_dir=output_dir, db_path=db_path)

    rows = PortfolioRepository(db_path).list_paper_decisions(user_id="u1", trade_date="2026-06-12")
    assert len(rows) == 1
    assert rows[0]["decision_id"]
    assert rows[0]["paper_action"] in {"paper_buy", "paper_hold", "paper_hold", "paper_risk_alert"}

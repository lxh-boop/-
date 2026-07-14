import pandas as pd

from app.classic_services import run_paper_trading_from_latest
from database.repositories import UserRepository


def test_ai_paper_trading_decision_reason_is_saved(tmp_path) -> None:
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
                "reason": "final recommendation reason",
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")
    repo = UserRepository(tmp_path / "agent_quant.db")
    repo.insert_user_profile({"user_id": "u1", "available_capital": 100000})

    run_paper_trading_from_latest("u1", top_k=1, output_dir=output_dir, db_path=tmp_path / "agent_quant.db")

    decisions = (output_dir / "portfolio" / "u1" / "ai_paper_decisions_latest.json").read_text(encoding="utf-8")
    assert "decision_id" in decisions
    assert "paper_buy" in decisions or "paper_hold" in decisions
    assert "调仓" in decisions
    assert "final recommendation reason" in decisions

import pandas as pd

from app.classic_services import run_paper_trading_from_latest
from database.repositories import UserRepository


def test_paper_trading_uses_final_action_but_keeps_original_ranking_input(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"rank": 1, "date": "2026-06-12", "code": "000001", "name": "A", "score": 0.95},
            {"rank": 2, "date": "2026-06-12", "code": "000002", "name": "B", "score": 0.90},
            {"rank": 3, "date": "2026-06-12", "code": "000003", "name": "C", "score": 0.85},
            {"rank": 4, "date": "2026-06-12", "code": "000004", "name": "D", "score": 0.80},
        ]
    ).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"stock_code": "000001", "stock_name": "A", "final_score": 0.9, "final_action": "keep", "target_weight": 0.05, "current_price": 10},
            {"stock_code": "000002", "stock_name": "B", "final_score": 0.8, "final_action": "exclude", "target_weight": 0.0, "current_price": 10},
            {"stock_code": "000003", "stock_name": "C", "final_score": 0.7, "final_action": "hold", "target_weight": 0.0, "current_price": 10},
            {"stock_code": "000004", "stock_name": "D", "final_score": 0.6, "final_action": "risk_alert", "target_weight": 0.0, "current_price": 10},
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")
    repo = UserRepository(tmp_path / "agent_quant.db")
    repo.insert_user_profile({"user_id": "u1", "available_capital": 100000})

    result = run_paper_trading_from_latest(
        user_id="u1",
        top_k=4,
        output_dir=output_dir,
        db_path=tmp_path / "agent_quant.db",
    )

    plan_actions = {item.stock_code: item.action for item in result.plan.decisions}
    assert plan_actions["000001"] == "buy"
    assert plan_actions["000002"] == "buy"
    assert plan_actions["000003"] == "buy"
    assert plan_actions["000004"] == "buy"
    assert all(order.is_paper_trading for order in result.orders)

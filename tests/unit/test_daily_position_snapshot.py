import pandas as pd
import os

from app.classic_services import list_daily_position_snapshot_dates, run_paper_trading_from_latest
from database.repositories import UserRepository


def test_daily_position_snapshot_is_created(tmp_path) -> None:
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
    UserRepository(tmp_path / "agent_quant.db").insert_user_profile({"user_id": "u1", "available_capital": 100000})

    run_paper_trading_from_latest("u1", top_k=1, output_dir=output_dir, db_path=tmp_path / "agent_quant.db")

    root = output_dir / "portfolio" / "u1"
    assert (root / "paper_account_latest.json").exists()
    assert (root / "paper_positions_latest.csv").exists()
    assert (root / "paper_orders_latest.csv").exists()
    assert (root / "portfolio_risk_report_latest.json").exists()
    assert (root / "history" / "positions" / "positions_20260612.csv").exists()
    assert "2026-06-12" in list_daily_position_snapshot_dates("u1", output_dir)


def test_paper_trading_from_latest_can_use_ranking_without_recommendations(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "rank": 1,
                "date": "2026-06-12",
                "code": "000001",
                "name": "A",
                "close": 10,
                "score": 0.9,
                "confidence": "中",
                "risk_level": "中",
            }
        ]
    ).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    UserRepository(tmp_path / "agent_quant.db").insert_user_profile({"user_id": "u1", "available_capital": 100000})

    result = run_paper_trading_from_latest("u1", top_k=1, output_dir=output_dir, db_path=tmp_path / "agent_quant.db")

    assert result.status == "success"
    root = output_dir / "portfolio" / "u1"
    assert (root / "paper_account_latest.json").exists()
    assert (root / "paper_positions_latest.csv").exists()
    assert (root / "history" / "positions" / "positions_20260612.csv").exists()


def test_paper_trading_prefers_newer_ranking_over_stale_recommendations(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "recommendations"
    rec_dir.mkdir(parents=True)
    ranking_path = output_dir / "ranking_latest.csv"
    recommendations_path = rec_dir / "final_recommendations_latest.csv"
    pd.DataFrame(
        [
            {
                "rank": 1,
                "date": "2026-06-23",
                "prediction_date": "2026-06-24",
                "code": "000001",
                "name": "A",
                "close": 10,
                "score": 0.9,
                "confidence": "中",
                "risk_level": "中",
            }
        ]
    ).to_csv(ranking_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "trade_date": "2026-06-18",
                "stock_code": "000002",
                "stock_name": "B",
                "target_weight": 0.05,
                "current_price": 10,
            }
        ]
    ).to_csv(recommendations_path, index=False, encoding="utf-8-sig")
    os.utime(recommendations_path, (1_000_000_000, 1_000_000_000))
    os.utime(ranking_path, (1_000_000_100, 1_000_000_100))
    UserRepository(tmp_path / "agent_quant.db").insert_user_profile({"user_id": "u1", "available_capital": 100000})

    result = run_paper_trading_from_latest("u1", top_k=1, output_dir=output_dir, db_path=tmp_path / "agent_quant.db")

    assert result.status == "success"
    root = output_dir / "portfolio" / "u1"
    assert (root / "history" / "positions" / "positions_20260624.csv").exists()
    assert not (root / "history" / "positions" / "positions_20260618.csv").exists()

from __future__ import annotations

from pathlib import Path

import pandas as pd

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def write_agent_fixture(
    tmp_path: Path,
    user_id: str = "u1",
    stock_code: str = "600519",
    price: float = 10.0,
    final_action: str = "keep",
    final_score: float = 0.80,
    rank: int = 1,
    cash: float = 100000.0,
    with_position: bool = False,
):
    position_adjustment_ratio = 0.80
    combined_adjustment = position_adjustment_ratio - 1.0
    output_dir = tmp_path / "outputs"
    rec_dir = output_dir / "users" / user_id / "recommendations"
    rec_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "rank": rank,
                "date": "2026-06-12",
                "code": stock_code,
                "name": "Kweichow Moutai",
                "close": price,
                "score": 0.90,
                "confidence": "high",
            },
            {
                "rank": 2,
                "date": "2026-06-12",
                "code": "000001",
                "name": "Ping An Bank",
                "close": 12.0,
                "score": 0.40,
                "confidence": "medium",
            },
        ]
    ).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "stock_code": stock_code,
                "stock_name": "Kweichow Moutai",
                "trade_date": "2026-06-12",
                "current_price": price,
                "original_score": final_score,
                "final_score": final_score,
                "final_action": final_action,
                "news_adjustment": 0.0,
                "effective_news_adjustment": 0.0,
                "user_adjustment": combined_adjustment,
                "combined_adjustment": combined_adjustment,
                "target_weight": 0.05,
                "position_adjustment_ratio": position_adjustment_ratio,
                "ai_reliability_weight": 0.00,
                "risk_warning": "hard risk" if final_action in {"exclude", "risk_alert"} else "",
                "triggered_rules": "[]",
                "evidence_news_ids": "[]",
                "evidence_chunk_ids": "[]",
                "reason": "fixture",
            },
            {
                "stock_code": "000001",
                "stock_name": "Ping An Bank",
                "trade_date": "2026-06-12",
                "current_price": 12.0,
                "original_score": 0.35,
                "news_adjustment": -0.2,
                "effective_news_adjustment": 0.0,
                "user_adjustment": -1.0,
                "combined_adjustment": -1.0,
                "position_adjustment_ratio": 0.0,
                "target_weight": 0.0,
                "risk_warning": "negative risk",
            },
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")
    db_path = tmp_path / "agent.db"
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / user_id)
    account = create_default_account(user_id, initial_cash=cash)
    storage.save_account(account)
    positions = []
    if with_position:
        positions.append(
            create_position(
                user_id=user_id,
                stock_code="000001",
                stock_name="Ping An Bank",
                quantity=1000,
                cost_price=12.0,
                current_price=12.0,
                total_assets=cash,
                industry="Bank",
            )
        )
    storage.save_positions(positions)
    return output_dir, db_path

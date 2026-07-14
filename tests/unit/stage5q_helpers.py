from __future__ import annotations

import csv
from pathlib import Path


def write_stage5q_inputs(
    root: Path,
    user_id: str = "u1",
    trade_date: str = "2026-04-01",
    count: int = 10,
    mismatch: bool = False,
) -> None:
    token = trade_date.replace("-", "")
    ranking_path = root / "rankings" / "history" / f"ranking_{token}.csv"
    rec_path = root / "users" / user_id / "recommendations" / f"final_recommendations_{token}.csv"
    ranking_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    ranking_rows = []
    rec_rows = []
    for index in range(1, count + 1):
        code = f"{index:06d}"
        price = 10.0 + index
        pred_score = 1.0 - index * 0.01
        ranking_rows.append(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "stock_name": f"S{index}",
                "rank": index,
                "pred_rank": index,
                "original_rank": index,
                "pred_score": pred_score,
                "original_score": pred_score,
                "current_price": price,
                "close": price,
                "model_name": "stored_model",
                "model_version": "v1",
            }
        )
        rec_rows.append(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "stock_name": f"S{index}",
                "rank": index,
                "original_pred_rank": index + (1 if mismatch and index == 1 else 0),
                "original_pred_score": pred_score,
                "final_score": 0.9 - index * 0.01,
                
                "target_weight": 0.08,
                "position_adjustment_ratio": 1.0,
                "ai_reliability_weight": 0.0,
                "current_price": price,
                "created_at": f"{trade_date} 15:00:00",
            }
        )
    for path, rows in [(ranking_path, ranking_rows), (rec_path, rec_rows)]:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

import pandas as pd

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_failed_day_carries_positions_forward(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    write_stage5q_inputs(tmp_path, trade_date="2026-04-02", count=30)
    (tmp_path / "users" / "u1" / "recommendations" / "final_recommendations_20260402.csv").unlink()

    run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-02",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        audit_log="required",
        continue_on_error=True,
    )

    day1 = pd.read_csv(tmp_path / "portfolio" / "u1" / "history" / "positions" / "positions_20260401.csv", dtype={"stock_code": str})
    day2 = pd.read_csv(tmp_path / "portfolio" / "u1" / "history" / "positions" / "positions_20260402.csv", dtype={"stock_code": str})
    assert not day1.empty
    assert set(day1["stock_code"]) == set(day2["stock_code"])
    assert day1["quantity"].astype(float).sum() == day2["quantity"].astype(float).sum()

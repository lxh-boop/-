import csv
import json
from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def _make_top10_unaffordable(root: Path) -> None:
    for path in list((root / "rankings" / "history").glob("ranking_*.csv")) + list((root / "users" / "u1" / "recommendations").glob("final_recommendations_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
            fieldnames = list(rows[0].keys())
        for row in rows[:10]:
            row["current_price"] = "2000"
            row["close"] = "2000"
        fieldnames = sorted(set(fieldnames) | {key for row in rows for key in row})
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def test_daily_audit_log_contains_weight_rounds(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    _make_top10_unaffordable(tmp_path)
    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        audit_log="required",
        continue_on_error=True,
    )
    payload = json.loads(next((Path(result.audit_log_dir) / "daily").glob("*.json")).read_text(encoding="utf-8"))
    assert payload["lot_execution"]["rounds"]
    assert payload["lot_execution"]["rounds"][0]["removed_stock_code"]

import json
from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_strategy_status_separate_from_reconciliation(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=10)

    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        strategy="fixed_original_top10_ai_weight",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        use_full_stored_ai_results=True,
        recursive_lot_reallocation=True,
        audit_log="required",
        continue_on_error=True,
    )
    payload = json.loads(next((Path(result.audit_log_dir) / "daily").glob("*.json")).read_text(encoding="utf-8"))

    assert payload["strategy_validation_status"] == "passed"
    assert payload["execution_status"] == "success"
    assert "account_reconciliation_status" in payload
    assert "position_reconciliation_status" in payload

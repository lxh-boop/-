from __future__ import annotations

from pipelines.full_replay_audit import audit_full_replay
from stage5q_helpers import write_stage5q_inputs


def test_daily_position_and_account_reconciliation_reports_missing_source(tmp_path) -> None:
    write_stage5q_inputs(tmp_path)
    result = audit_full_replay("u1", "2026-04-01", "2026-04-01", output_dir=tmp_path)
    assert result.account_reconciliation_failed_day_count >= 0
    assert result.total_trading_days == 1

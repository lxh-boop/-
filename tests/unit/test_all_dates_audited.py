from __future__ import annotations

from pipelines.full_replay_audit import audit_full_replay
from stage5q_helpers import write_stage5q_inputs


def test_all_dates_audited(tmp_path) -> None:
    write_stage5q_inputs(tmp_path)
    result = audit_full_replay("u1", "2026-04-01", "2026-04-01", output_dir=tmp_path)
    assert result.total_trading_days == 1
    assert result.original_ranking_day_count == 1
    assert result.ai_adjustment_day_count == 1
    assert "full_replay_audit.csv" in result.daily_report_path

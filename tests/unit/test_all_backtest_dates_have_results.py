from pipelines.daily_result_source_audit import audit_daily_result_sources
from stage5q_helpers import write_stage5q_inputs


def test_all_backtest_dates_have_results(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    write_stage5q_inputs(tmp_path, trade_date="2026-04-02", count=30)

    result = audit_daily_result_sources(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-02",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
    )

    assert result.total_trading_days == 2
    assert result.ready_day_count == 2
    assert result.failed_continue_day_count == 0

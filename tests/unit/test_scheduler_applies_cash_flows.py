from portfolio.cash_flow import add_cash_flow
from scheduler.user_job_runner import apply_due_cash_flows_for_user


def test_scheduler_applies_due_cash_flows(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    add_cash_flow("u1", "deposit", 50000, "2026-05-04", output_dir=output_dir, use_database=False)

    result = apply_due_cash_flows_for_user(
        "u1",
        "2026-05-04",
        output_dir=output_dir,
        db_path=tmp_path / "db.sqlite",
        dry_run=False,
    )

    assert result["applied_cash_flow_count"] == 1
    assert result["cash"] == 150000

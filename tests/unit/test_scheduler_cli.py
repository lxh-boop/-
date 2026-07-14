from scheduler import scheduler_cli
from scheduler.schemas import SchedulerStatus


class _FakeJob:
    overall_status = SchedulerStatus.SUCCESS

    def to_dict(self):
        return {"overall_status": self.overall_status, "trade_date": "2026-06-11"}


def test_scheduler_cli_run_uses_worker(monkeypatch, capsys) -> None:
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return _FakeJob()

    monkeypatch.setattr(scheduler_cli, "run_scheduled_daily_update", fake_run)

    exit_code = scheduler_cli.main(["run", "--trade-date", "2026-06-11", "--all-users", "--dry-run", "--source", "manual"])

    assert exit_code == 0
    assert seen["trade_date"] == "2026-06-11"
    assert seen["dry_run"] is True
    assert seen["user_ids"] is None
    assert "2026-06-11" in capsys.readouterr().out


def test_scheduler_cli_status_prints_latest_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(scheduler_cli, "load_latest_job_status", lambda _: {"overall_status": "success"})

    assert scheduler_cli.main(["status"]) == 0
    assert "success" in capsys.readouterr().out

from __future__ import annotations

from agent.report_tool import list_reports, read_latest_report, read_report_by_date


def test_report_tool_lists_and_reads_reports(tmp_path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "daily_pipeline_report_20260611.md").write_text("# 20260611", encoding="utf-8")

    listed = list_reports(tmp_path)
    assert listed["count"] == 1
    assert read_latest_report(tmp_path)["text"] == "# 20260611"
    assert read_report_by_date("2026-06-11", tmp_path)["ok"] is True

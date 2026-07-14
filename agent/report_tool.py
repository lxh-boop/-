from __future__ import annotations

from pathlib import Path
from typing import Any

from scoring.schemas import COMPLIANCE_DISCLAIMER


def _report_dir(output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "reports"


def list_reports(output_dir: str | Path = "outputs") -> dict[str, Any]:
    report_dir = _report_dir(output_dir)
    rows = []
    if report_dir.exists():
        for path in sorted(report_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            rows.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "modified_at": stat.st_mtime,
                    "size": stat.st_size,
                }
            )
    return {
        "ok": bool(rows),
        "reports": rows,
        "count": len(rows),
        "message": "reports loaded" if rows else "no report files found",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def read_latest_report(output_dir: str | Path = "outputs") -> dict[str, Any]:
    reports = list_reports(output_dir=output_dir).get("reports") or []
    if not reports:
        return {
            "ok": False,
            "text": "",
            "message": "no report files found",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    return _read_report_path(Path(reports[0]["path"]))


def read_report_by_date(date: str, output_dir: str | Path = "outputs") -> dict[str, Any]:
    token = str(date or "").replace("-", "")
    for path in _report_dir(output_dir).glob("*.md"):
        if token and token in path.stem:
            return _read_report_path(path)
    return {
        "ok": False,
        "text": "",
        "message": f"no report found for date={date}",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def _read_report_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "ok": False,
            "path": str(path),
            "text": "",
            "message": "report file not found",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    return {
        "ok": True,
        "path": str(path),
        "text": path.read_text(encoding="utf-8", errors="ignore"),
        "message": "report loaded",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }

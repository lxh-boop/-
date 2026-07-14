from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.multi_agent.metrics import METRIC_DEFINITIONS
from evaluation.multi_agent.schemas import BenchmarkRunResult


DISCLAIMER = "\u672c\u9879\u76ee\u4ec5\u7528\u4e8e\u673a\u5668\u5b66\u4e60\u3001\u91d1\u878d\u6570\u636e\u5206\u6790\u548c\u9879\u76ee\u5c55\u793a\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\uff0c\u4e0d\u7528\u4e8e\u5b9e\u76d8\u4ea4\u6613\u3002"


def _summary_rows(results: list[BenchmarkRunResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        rows.append(
            {
                "scenario_id": item.scenario_id,
                "scenario_name": item.scenario_name,
                "mode": item.mode,
                "success": item.success,
                "execution_status": item.execution_status,
                "latency_seconds": item.latency_seconds,
                "task_count": item.task_count,
                "successful_task_count": item.successful_task_count,
                "tool_call_count": item.tool_call_count,
                "permission_violation_count": item.permission_violation_count,
                "structured_output_valid": item.structured_output_valid,
                "handoff_expected_count": item.handoff_expected_count,
                "handoff_completed_count": item.handoff_completed_count,
                "missing_handoff_count": item.missing_handoff_count,
                "evidence_source_count": item.evidence_source_count,
                "evidence_source_coverage": item.evidence_source_coverage,
                "partial_failure_expected": item.partial_failure_expected,
                "partial_failure_recovered": item.partial_failure_recovered,
                "decision_source": item.decision_source,
                "route_correct": item.route_correct,
                "safety_route_correct": item.safety_route_correct,
                "llm_planner_called": item.llm_planner_called,
                "semantic_observer_triggered": item.semantic_observer_triggered,
                "replan_triggered": item.replan_triggered,
                "invalid_replan_block_count": item.invalid_replan_block_count,
                "error_count": len(item.errors),
            }
        )
    return rows


def _write_csv(path: Path, results: list[BenchmarkRunResult]) -> None:
    rows = _summary_rows(results)
    fieldnames = list(rows[0]) if rows else ["scenario_id", "mode"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _format_metric_table(metrics: dict[str, Any]) -> list[str]:
    lines = ["| Metric | Value |", "| --- | ---: |"]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value} |")
    return lines


def _write_markdown(path: Path, payload: dict[str, Any], results: list[BenchmarkRunResult]) -> None:
    failed = [
        item
        for item in results
        if (
            not item.success
            or not item.structured_output_valid
            or item.permission_violation_count
            or item.missing_handoff_count
        )
    ]
    lines: list[str] = [
        "# Multi-Agent Benchmark Report",
        "",
        DISCLAIMER,
        "",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Overall Metrics",
        "",
        *_format_metric_table(payload.get("metrics") or {}),
        "",
        "## Metrics By Mode",
        "",
    ]
    for mode, metrics in (payload.get("metrics_by_mode") or {}).items():
        lines.extend([f"### {mode}", "", *_format_metric_table(metrics), ""])

    lines.extend(["## Metric Definitions", ""])
    for key, definition in METRIC_DEFINITIONS.items():
        lines.append(f"- `{key}`: {definition}")

    lines.extend(["", "## Scenario Summary", ""])
    lines.append("| Scenario | Mode | Success | Status | Tools | Sources | Permission Violations | Missing Handoffs |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |")
    for item in results:
        lines.append(
            "| "
            f"{item.scenario_id} | {item.mode} | {item.success} | {item.execution_status} | "
            f"{item.tool_call_count} | {item.evidence_source_count} | "
            f"{item.permission_violation_count} | {item.missing_handoff_count} |"
        )

    lines.extend(["", "## Failure / Diagnostic Cases", ""])
    if not failed:
        lines.append("No failed diagnostic cases were detected.")
    else:
        for item in failed:
            reasons = []
            if not item.success:
                reasons.append("run_not_successful")
            if not item.structured_output_valid:
                reasons.extend(item.structured_output_errors)
            if item.permission_violation_count:
                reasons.append(f"permission_violations={item.permission_violation_count}")
            if item.missing_handoff_count:
                reasons.append(f"missing_handoffs={item.missing_handoff_count}")
            lines.append(f"- `{item.scenario_id}` / `{item.mode}`: {', '.join(reasons)}")

    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "The benchmark compares the direct tool path with the read-only Supervisor + Specialist path using fixed fixture data. "
            "Write/execute/commit tools are not invoked by the benchmark runner.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def export_benchmark(
    *,
    output_root: str | Path,
    payload: dict[str, Any],
    results: list[BenchmarkRunResult],
) -> dict[str, str]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    details_path = root / "benchmark_details.json"
    csv_path = root / "benchmark_summary.csv"
    report_path = root / "benchmark_report.md"
    metrics_path = root / "benchmark_metrics.json"

    details_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    metrics_path.write_text(
        json.dumps(
            {
                "metrics": payload.get("metrics") or {},
                "metrics_by_mode": payload.get("metrics_by_mode") or {},
                "definitions": METRIC_DEFINITIONS,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    _write_csv(csv_path, results)
    _write_markdown(report_path, payload, results)
    return {
        "details_json": str(details_path),
        "summary_csv": str(csv_path),
        "report_markdown": str(report_path),
        "metrics_json": str(metrics_path),
    }

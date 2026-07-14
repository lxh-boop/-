from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


METRICS_TO_COMPARE = [
    "recall_at_5",
    "recall_at_10",
    "mrr",
    "ndcg_at_10",
    "id_context_precision",
    "id_context_recall",
    "context_precision",
    "context_recall",
    "content_faithfulness",
    "response_relevancy",
    "future_leak_rate",
    "wrong_stock_rate",
    "duplicate_event_rate",
    "direct_evidence_rate",
    "p95_latency_ms",
]


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_cases(summary_path: Path) -> dict[str, dict[str, Any]]:
    path = summary_path.parent / "case_results.jsonl"
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                row = json.loads(line)
                rows[str(row.get("case_id"))] = row
    return rows


def _metric(summary: dict[str, Any], name: str) -> float | None:
    if name == "p95_latency_ms":
        value = summary.get(name)
    else:
        value = (summary.get("average_metrics") or {}).get(name)
    return float(value) if isinstance(value, int | float) else None


def _label_delta(name: str, baseline: float | None, candidate: float | None) -> str:
    if baseline is None or candidate is None:
        return "无数据"
    if abs(candidate - baseline) < 1e-12:
        return "持平"
    lower_is_better = name in {"future_leak_rate", "wrong_stock_rate", "duplicate_event_rate", "p95_latency_ms"}
    improved = candidate < baseline if lower_is_better else candidate > baseline
    return "提升" if improved else "下降"


def compare(baseline: str | Path, candidate: str | Path, *, output_dir: str | Path | None = None) -> Path:
    baseline_path = Path(baseline)
    candidate_path = Path(candidate)
    baseline_summary = _load_json(baseline_path)
    candidate_summary = _load_json(candidate_path)
    target_dir = Path(output_dir) if output_dir else candidate_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for metric in METRICS_TO_COMPARE:
        base_value = _metric(baseline_summary, metric)
        candidate_value = _metric(candidate_summary, metric)
        rows.append({
            "metric": metric,
            "baseline": base_value,
            "candidate": candidate_value,
            "delta": None if base_value is None or candidate_value is None else candidate_value - base_value,
            "status": _label_delta(metric, base_value, candidate_value),
        })

    baseline_cases = _load_cases(baseline_path)
    candidate_cases = _load_cases(candidate_path)
    base_success = {case_id for case_id, row in baseline_cases.items() if not row.get("error")}
    cand_success = {case_id for case_id, row in candidate_cases.items() if not row.get("error")}
    all_cases = set(baseline_cases) | set(candidate_cases)
    case_groups = {
        "共同成功案例": sorted(base_success & cand_success),
        "基准成功但候选失败案例": sorted(base_success - cand_success),
        "基准失败但候选成功案例": sorted(cand_success - base_success),
        "两个版本都失败的案例": sorted(all_cases - base_success - cand_success),
    }

    csv_path = target_dir / "experiment_comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["metric", "baseline", "candidate", "delta", "status"])
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Ragas 实验对比",
        "",
        f"- Baseline: {baseline_path}",
        f"- Candidate: {candidate_path}",
        "",
        "## 指标变化",
    ]
    for row in rows:
        lines.append(f"- {row['metric']}: {row['baseline']} -> {row['candidate']} ({row['status']})")
    lines.append("")
    lines.append("## 案例集合")
    for name, cases in case_groups.items():
        lines.append(f"- {name}: {len(cases)}")
        if cases:
            lines.append(f"  - {', '.join(cases[:30])}")
    report_path = target_dir / "experiment_comparison.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two RAG evaluation experiments.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)
    report = compare(args.baseline, args.candidate, output_dir=args.output_dir or None)
    print(f"experiment comparison written: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

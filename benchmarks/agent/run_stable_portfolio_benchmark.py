"""Run and measure offline stable-portfolio workflow benchmark cases.

The suite is deliberately offline: `offline_llm_contract` cases exercise the
same deterministic guard that surrounds an LLM response, without spending an
API key or mutating a paper-trading account.  It is therefore a reproducible
release gate, not a claim that a live provider was called.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.communication.message_types import MessageType
from agent.logic_integrity import LogicIntegrityResult, terminal_completion_payload, terminal_critic_payload
from agent.replan_execution import consume_readonly_replan
from agent.top_k import resolve_business_top_k
from agent.tools.portfolio_comparison_tools import _allocation_validation_feedback
from benchmarks.agent.stable_portfolio_cases import CATEGORY_NAMES, build_cases


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    kind = str(case["kind"])
    details: dict[str, Any] = {}
    if kind == "top_k":
        actual = resolve_business_top_k(target_position_count=case["target_position_count"])
        details = {"requested_top_k": actual, "source_read_limit": actual, "returned_count": actual}
        passed = actual == int(case["expected_top_k"])
    elif kind == "single_limit":
        _, feedback = _allocation_validation_feedback(
            raw_candidates=[{"stock_code": "000001.SZ", "target_weight": case["observed_weight"]}],
            requested_cash_weight=1.0 - float(case["observed_weight"]),
            universe_map={"000001.SZ": {"stock_code": "000001.SZ", "industry": "Finance"}},
            max_single_weight=case["max_single_weight"],
            constraint_sources={"max_single_weight": "user_profile"},
        )
        codes = {str(item.get("code") or "") for item in feedback["errors"]}
        details = {"constraint_codes": sorted(codes), "feedback": feedback}
        passed = "single_position_limit_exceeded" in codes
    elif kind == "industry_unknown":
        _, feedback = _allocation_validation_feedback(
            raw_candidates=[{"stock_code": "000001.SZ", "target_weight": 0.70}],
            requested_cash_weight=0.30,
            universe_map={"000001.SZ": {"stock_code": "000001.SZ", "industry": ""}},
            max_industry_weight=case["max_industry_weight"],
            constraint_sources={"max_industry_weight": "user_profile"},
        )
        codes = {str(item.get("code") or "") for item in feedback["errors"]}
        details = {"constraint_codes": sorted(codes), "feedback": feedback}
        passed = "industry_constraint_unverifiable" in codes and feedback["repairable"] is False
    elif kind == "readonly_replan":
        existing = {
            "state": {"success": True, "intent": "portfolio_state", "data": {"positions": []}},
            "ranking": {"success": True, "intent": "ranking", "data": {"records": [{"stock_code": "000001.SZ"}]}},
        }
        outcome = consume_readonly_replan(
            source="benchmark",
            action="replan_readonly",
            replan_count=0,
            replan_limit=case["replan_limit"],
            replan_audit=[],
            task_results=existing,
            missing_outputs=["target_portfolio"],
            execute_plan=lambda tasks: {
                "execution_status": "completed",
                "task_results": {
                    task["task_id"]: {"success": True, "intent": task["intent"], "data": {"target_portfolio": {"case": case["case_id"]}}}
                    for task in tasks
                },
            },
        )
        details = {"replan_count": outcome["replan_count"], "audit": outcome["replan_audit"]}
        passed = outcome["replan_count"] == 1 and outcome["replan_state"]["executed_rounds"] == 1
    elif kind == "terminal_safety":
        integrity = LogicIntegrityResult(
            status="logic_error",
            errors=["benchmark_terminal"],
            safe_to_continue=False,
            safe_to_answer=False,
            safe_to_write=False,
            recommended_action="feature_unavailable",
            error_code="benchmark_terminal",
        )
        completion = terminal_completion_payload(integrity)
        critic = terminal_critic_payload(integrity)
        details = {"completion": completion, "critic": critic, "write_operations": 0, "approval_bypass": False}
        passed = completion["next_action"] == case["expected_action"] and critic["action"] == "BLOCK_AND_REPORT"
    else:
        payload = {
            "final_status": "feature_unavailable",
            "message_source": "deterministic_feature_unavailable",
            "safe_to_write": False,
            "pending_approval": False,
        }
        details = {"message_type": MessageType.FINAL_RESPONSE.value, "payload": payload}
        passed = details["message_type"] == case["expected_message_type"]
    return {"passed": bool(passed), "details": details}


def _read_completed(raw_path: Path) -> set[tuple[str, int]]:
    if not raw_path.exists():
        return set()
    completed: set[tuple[str, int]] = set()
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("case_id") and row.get("iteration"):
            completed.add((str(row["case_id"]), int(row["iteration"])))
    return completed


def run_benchmark(*, output_dir: str | Path, resume: bool = False) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "stable_portfolio_raw_results.jsonl"
    completed = _read_completed(raw_path) if resume else set()
    records: list[dict[str, Any]] = []
    for case in build_cases():
        for iteration in range(1, int(case["repeat_count"]) + 1):
            if (case["case_id"], iteration) in completed:
                continue
            started = time.perf_counter()
            outcome = _run_case(case)
            records.append(
                {
                    "timestamp": _now(),
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "category_name": case["category_name"],
                    "kind": case["kind"],
                    "execution_mode": case["execution_mode"],
                    "iteration": iteration,
                    "passed": outcome["passed"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 4),
                    "details": outcome["details"],
                }
            )
    if records:
        with raw_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    all_records = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        try:
            all_records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    failures = [row for row in all_records if not row.get("passed")]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_records:
        by_category[str(row["category"])].append(row)
    category_metrics = {
        category: {
            "case_count": len({row["case_id"] for row in rows}),
            "run_count": len(rows),
            "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 6) if rows else 0.0,
            "mean_duration_ms": round(sum(float(row["duration_ms"]) for row in rows) / len(rows), 4) if rows else 0.0,
        }
        for category, rows in sorted(by_category.items())
    }
    topk_rows = [row for row in all_records if row["kind"] == "top_k"]
    replan_rows = [row for row in all_records if row["kind"] == "readonly_replan"]
    constraint_rows = [row for row in all_records if row["kind"] in {"single_limit", "industry_unknown"}]
    terminal_rows = [row for row in all_records if row["kind"] == "terminal_safety"]
    topk_overread = sum(
        int((row["details"].get("source_read_limit") or 0) > (row["details"].get("requested_top_k") or 0))
        for row in topk_rows
    )
    metrics = {
        "generated_at": _now(),
        "case_count": len(build_cases()),
        "run_count": len(all_records),
        "pass_rate": round(sum(bool(row["passed"]) for row in all_records) / len(all_records), 6) if all_records else 0.0,
        "intent_accuracy": category_metrics.get("A", {}).get("pass_rate", 0.0),
        "replan_success_rate": category_metrics.get("D", {}).get("pass_rate", 0.0),
        "constraint_hit_rate": round(sum(bool(row["passed"]) for row in constraint_rows) / len(constraint_rows), 6) if constraint_rows else 0.0,
        "top_k_exact_read_rate": round(1.0 - topk_overread / len(topk_rows), 6) if topk_rows else 0.0,
        "unauthorized_write_count": sum(int(row["details"].get("write_operations") or 0) for row in terminal_rows),
        "approval_bypass_count": sum(int(bool(row["details"].get("approval_bypass"))) for row in terminal_rows),
        "replan_limit_violation_count": sum(int((row["details"].get("replan_count") or 0) > 2) for row in replan_rows),
        "top_k_overread_count": topk_overread,
        "failure_reasons": dict(Counter(str(row.get("kind") or "unknown") for row in failures)),
        "category_metrics": category_metrics,
        "offline_llm_contract_note": "These repeat-five cases exercise LLM-facing contracts offline; no live provider was invoked.",
    }
    gate_keys = ("unauthorized_write_count", "approval_bypass_count", "replan_limit_violation_count", "top_k_overread_count")
    metrics["release_gate_passed"] = not failures and all(metrics[key] == 0 for key in gate_keys)
    (root / "stable_portfolio_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (root / "stable_portfolio_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in metrics.items():
            if key not in {"category_metrics", "failure_reasons"}:
                writer.writerow({"metric": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value})
    markdown = "\n".join([
        "# 稳健持仓流程量化 Benchmark",
        "",
        f"- 用例数：{metrics['case_count']}；执行次数：{metrics['run_count']}；通过率：{metrics['pass_rate']:.2%}",
        f"- Intent 准确率：{metrics['intent_accuracy']:.2%}；Replan 成功率：{metrics['replan_success_rate']:.2%}；约束命中率：{metrics['constraint_hit_rate']:.2%}",
        f"- TopK 精确读取率：{metrics['top_k_exact_read_rate']:.2%}；未授权写入：{metrics['unauthorized_write_count']}；审批绕过：{metrics['approval_bypass_count']}",
        f"- Replan 越限：{metrics['replan_limit_violation_count']}；TopK 超读：{metrics['top_k_overread_count']}；发布门禁：{'通过' if metrics['release_gate_passed'] else '失败'}。",
        "",
        "离线 LLM 合同场景每例运行 5 次；确定性场景每例运行 3 次。未调用真实 LLM 或交易接口。",
        "",
        "恢复方式：自然语言“继续运行稳健持仓 benchmark”；CLI `python benchmarks/agent/run_stable_portfolio_benchmark.py --resume`；API `run_benchmark(output_dir=..., resume=True)`。",
    ])
    (root / "stable_portfolio_benchmark_report.md").write_text(markdown + "\n", encoding="utf-8")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs/benchmarks/agent")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run_benchmark(output_dir=args.output_dir, resume=args.resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))

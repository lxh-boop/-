from __future__ import annotations

import csv
import json
import platform
import statistics
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.ragas_eval.config import RagasEvalConfig
from evaluation.ragas_eval.ragas_metrics import get_ragas_version
from evaluation.ragas_eval.schemas import CaseRunResult


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _metric_average(results: list[CaseRunResult]) -> dict[str, Any]:
    values: dict[str, list[float]] = {}
    for result in results:
        for key, value in result.metrics.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                values.setdefault(key, []).append(float(value))
    return {key: sum(items) / len(items) for key, items in sorted(values.items()) if items}


def evaluate_quality_gates(averages: dict[str, Any], gates: dict[str, dict[str, float]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    overall_passed = True
    for metric, rule in (gates or {}).items():
        value = averages.get(metric)
        if value is None:
            rows.append({"metric": metric, "status": "not_evaluated", "value": None, "rule": rule})
            continue
        status = "passed"
        if "max" in rule and float(value) > float(rule["max"]):
            status = "failed"
        if "min" in rule and float(value) < float(rule["min"]):
            status = "failed"
        if status == "failed":
            overall_passed = False
        rows.append({"metric": metric, "status": status, "value": value, "rule": rule})
    return {"overall_passed": overall_passed, "items": rows}


def _is_diagnostic_dataset(results: list[CaseRunResult]) -> bool:
    if not results:
        return False
    for result in results:
        metadata = result.case.metadata or {}
        tags = set(result.case.tags or [])
        if (
            metadata.get("gold_level") == "diagnostic_not_human_gold"
            or metadata.get("source") == "auto_seed_from_local_news_chunk"
            or "auto_seed" in tags
        ):
            return True
    return False


def _formal_acceptance_eligibility(
    results: list[CaseRunResult],
    failed_cases: list[dict[str, Any]],
    dataset_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    if _is_diagnostic_dataset(results):
        return {
            "eligible": False,
            "dataset_class": "diagnostic",
            "reasons": ["diagnostic auto-seed dataset cannot be used for real quality acceptance"],
        }
    if len(results) < 30:
        reasons.append(f"formal acceptance requires at least 30 cases; got {len(results)}")
    if failed_cases or dataset_errors:
        reasons.append(
            f"formal acceptance requires zero failed cases and dataset errors; "
            f"got failures={len(failed_cases)} dataset_errors={len(dataset_errors)}"
        )

    answerable = [item for item in results if "no_answer" not in set(item.case.tags or [])]
    if len(answerable) < 30:
        reasons.append(f"formal acceptance requires at least 30 answerable cases; got {len(answerable)}")
    allowed_gold_levels = {"manual_reference", "manual_reviewed_reference", "human_reviewed_gold"}
    invalid_gold = [
        item.case.case_id
        for item in results
        if str((item.case.metadata or {}).get("gold_level") or "") not in allowed_gold_levels
    ]
    if invalid_gold:
        reasons.append(f"cases without accepted manual gold metadata: {', '.join(invalid_gold[:5])}")
    missing_references = [item.case.case_id for item in results if not item.case.reference]
    if missing_references:
        reasons.append(f"cases without reference answers: {', '.join(missing_references[:5])}")
    missing_reference_ids = [item.case.case_id for item in answerable if not item.case.reference_context_ids]
    if missing_reference_ids:
        reasons.append(f"answerable cases without reference_context_ids: {', '.join(missing_reference_ids[:5])}")
    non_full_text_gold = [
        item.case.case_id
        for item in answerable
        if str((item.case.metadata or {}).get("reference_content_level") or "") != "full_text"
    ]
    if non_full_text_gold:
        reasons.append(f"answerable cases without full-text gold evidence: {', '.join(non_full_text_gold[:5])}")

    uncaptured = [
        item.case.case_id
        for item in results
        if not item.case.actual_response
        or item.case.response_source != "production_agent_runtime"
        or not item.answer_metadata.get("uses_captured_actual_response")
    ]
    if uncaptured:
        reasons.append(f"cases without captured production Agent responses: {', '.join(uncaptured[:5])}")
    bad_normalization = [
        item.case.case_id
        for item in results
        if item.answer_metadata.get("normalization_method") != "deterministic_boilerplate_removal"
    ]
    if bad_normalization:
        reasons.append(f"cases with non-deterministic response normalization: {', '.join(bad_normalization[:5])}")

    required_metrics = ["context_precision", "context_recall", "content_faithfulness", "response_relevancy"]
    for metric in required_metrics:
        scored = [item for item in results if isinstance(item.metrics.get(metric), int | float)]
        if len(scored) < 30:
            reasons.append(f"metric {metric} requires at least 30 scored cases; got {len(scored)}")
    semantic_embedding_cases = [
        item
        for item in results
        if item.metrics.get("embedding_backend") in {"local_sentence_transformers", "openai_compatible"}
        and item.metrics.get("answer_relevancy_status") == "success"
    ]
    if len(semantic_embedding_cases) < 30:
        reasons.append(
            "response relevancy requires real semantic embeddings for at least 30 cases; "
            f"got {len(semantic_embedding_cases)}"
        )
    return {
        "eligible": not reasons,
        "dataset_class": "formal_candidate",
        "reasons": reasons,
        "answerable_case_count": len(answerable),
    }


def _make_report(
    config: RagasEvalConfig,
    summary: dict[str, Any],
    quality_report: dict[str, Any],
    results: list[CaseRunResult],
) -> str:
    averages = summary.get("average_metrics") or {}
    failed_gates = [item for item in quality_report.get("items", []) if item.get("status") == "failed"]
    future_cases = [
        result.case.case_id for result in results
        if (result.metrics.get("future_leak_count") or 0) > 0
    ]
    wrong_stock_cases = [
        result.case.case_id for result in results
        if (result.metrics.get("wrong_stock_count") or 0) > 0
    ]
    worst = sorted(
        results,
        key=lambda item: (
            item.metrics.get("id_context_recall") is None,
            item.metrics.get("id_context_recall") if item.metrics.get("id_context_recall") is not None else 1.0,
            item.latency_ms,
        ),
    )[:10]
    lines = [
        "# Ragas 离线评测报告",
        "",
        "## 实验配置",
        f"- 实验名称：{config.experiment_name}",
        f"- 模式：{config.mode}",
        f"- TopK：{config.top_k}",
        f"- 是否调用外部评测模型：{not config.runtime.no_llm and bool(config.runtime.api_key)}",
        "",
        "## 总体指标",
    ]
    if averages:
        for key, value in averages.items():
            lines.append(f"- {key}: {value:.6f}" if isinstance(value, float) else f"- {key}: {value}")
    else:
        lines.append("- 暂无可聚合指标。")
    lines += [
        "",
        "## 未通过质量门槛",
    ]
    if failed_gates:
        for item in failed_gates:
            lines.append(f"- 失败：{item['metric']} = {item['value']}，规则 {item['rule']}")
    else:
        lines.append("- 无。")
    lines += [
        "",
        "## 最差样本 Top10",
    ]
    for item in worst:
        lines.append(f"- {item.case.case_id}: id_context_recall={item.metrics.get('id_context_recall')}, error={item.error or '-'}")
    lines += [
        "",
        "## 未来信息泄漏案例",
        "- " + (", ".join(future_cases) if future_cases else "无。"),
        "",
        "## 错误股票关联案例",
        "- " + (", ".join(wrong_stock_cases) if wrong_stock_cases else "无。"),
        "",
        "## 高召回低精度案例",
        "- 第一版报告仅列出逐样本结果，请结合 case_results.jsonl 排查。",
        "",
        "## 高相关但低 Content Faithfulness 案例",
        "- 仅在配置 Ragas LLM-based 指标后可分析；该指标只作用于确定性清理后的实际回答内容。",
        "",
        "## 与基准实验的变化",
        "- 请使用 compare_experiments 命令生成对比报告。",
        "",
        "## 下一步建议",
        "- 补充人工审核 reference_context_ids 和 reference。",
        "- 配置评测模型后小批量运行 content_faithfulness/response_relevancy。",
    ]
    return "\n".join(lines) + "\n"


def export_results(
    *,
    output_dir: str | Path,
    config: RagasEvalConfig,
    results: list[CaseRunResult],
    failed_cases: list[dict[str, Any]],
    dataset_errors: list[dict[str, Any]],
    dataset_warnings: list[dict[str, Any]],
    start_time: datetime,
    end_time: datetime,
) -> tuple[Path, dict[str, Any]]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    records = [result.to_json_record() for result in results]
    _write_jsonl(root / "case_results.jsonl", records)
    _write_jsonl(root / "failed_cases.jsonl", failed_cases + dataset_errors)

    csv_fields = [
        "case_id",
        "user_input",
        "stock_code",
        "decision_time",
        "response",
        "retrieved_context_ids",
        "reference_context_ids",
        "latency_ms",
        "error",
    ]
    metric_keys = sorted({key for result in results for key in result.metrics})
    with (root / "case_results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=csv_fields + metric_keys)
        writer.writeheader()
        for result in records:
            row = {key: result.get(key, "") for key in csv_fields}
            row["response"] = str(row["response"])[:500]
            row["retrieved_context_ids"] = json.dumps(row["retrieved_context_ids"], ensure_ascii=False)
            row["reference_context_ids"] = json.dumps(row["reference_context_ids"], ensure_ascii=False)
            for key in metric_keys:
                row[key] = (result.get("metrics") or {}).get(key)
            writer.writerow(row)

    latencies = [float(result.latency_ms or 0.0) for result in results]
    averages = _metric_average(results)
    quality_report = evaluate_quality_gates(averages, config.quality_gates)
    eligibility = _formal_acceptance_eligibility(results, failed_cases, dataset_errors)
    if not eligibility["eligible"]:
        quality_report = {
            **quality_report,
            "overall_passed": None,
            "acceptance_eligible": False,
            "dataset_class": eligibility["dataset_class"],
            "reason": "; ".join(eligibility["reasons"]),
            "eligibility_details": eligibility,
        }
    else:
        quality_report = {
            **quality_report,
            "acceptance_eligible": True,
            "dataset_class": "formal_acceptance",
            "eligibility_details": eligibility,
        }
    api_call_count = int(sum(float(result.metrics.get("ragas_estimated_llm_call_count") or 0.0) for result in results))
    summary = {
        "experiment_name": config.experiment_name,
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "sample_count": len(results) + len(dataset_errors),
        "success_count": len([item for item in results if not item.error]),
        "failure_count": len(failed_cases) + len(dataset_errors),
        "ragas_version": get_ragas_version(),
        "python_version": platform.python_version(),
        "git_commit": _git_commit(),
        "retrieval_config": {"top_k": config.top_k, "decision_time_filter": config.decision_time_filter},
        "eval_model": config.runtime.sanitized(),
        "average_metrics": averages,
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0),
        "api_call_count": api_call_count,
        "estimated_token_usage": {},
        "quality_gates": quality_report,
        "dataset_warnings": dataset_warnings,
    }
    environment = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": summary["git_commit"],
        "ragas_version": get_ragas_version(),
        "runtime_config": config.runtime.sanitized(),
    }
    _write_json(root / "summary.json", summary)
    _write_json(root / "quality_gate_report.json", quality_report)
    _write_json(root / "environment.json", environment)
    try:
        import yaml

        (root / "run_config_snapshot.yaml").write_text(yaml.safe_dump(config.snapshot(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception:
        _write_json(root / "run_config_snapshot.yaml", config.snapshot())
    (root / "experiment_report.md").write_text(_make_report(config, summary, quality_report, results), encoding="utf-8")
    return root, summary

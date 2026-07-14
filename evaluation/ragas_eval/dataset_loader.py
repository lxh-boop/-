from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.ragas_eval.schemas import DatasetLoadResult, EvaluationCase


def load_jsonl_dataset(
    path: str | Path,
    *,
    case_id: str | None = None,
    limit: int | None = None,
    fail_fast: bool = False,
) -> DatasetLoadResult:
    dataset_path = Path(path)
    cases: list[EvaluationCase] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()

    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
                if not isinstance(raw, dict):
                    raise ValueError("each JSONL line must be an object")
                item = EvaluationCase.from_mapping(raw)
                if case_id and item.case_id != case_id:
                    continue
                if item.case_id in seen:
                    raise ValueError(f"duplicate case_id: {item.case_id}")
                seen.add(item.case_id)
                cases.append(item)
                for warning in item.warnings:
                    warnings.append({"case_id": item.case_id, "line_no": line_no, "warning": warning})
                if limit is not None and len(cases) >= int(limit):
                    break
            except Exception as exc:
                error = {
                    "line_no": line_no,
                    "case_id": raw.get("case_id") if isinstance(raw, dict) else "",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                errors.append(error)
                if fail_fast:
                    raise

    if case_id and not cases:
        errors.append({
            "line_no": 0,
            "case_id": case_id,
            "error_type": "CaseNotFound",
            "error": f"case_id={case_id} not found in dataset",
        })

    return DatasetLoadResult(cases=cases, errors=errors, warnings=warnings)

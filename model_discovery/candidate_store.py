from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .model_candidate_schema import CANDIDATE_FIELDS, ModelCandidate, normalize_candidate


DISCOVERY_OUTPUT_DIR = Path("outputs") / "model_discovery"
CANDIDATES_CSV = DISCOVERY_OUTPUT_DIR / "model_candidates.csv"
CANDIDATES_JSON = DISCOVERY_OUTPUT_DIR / "model_candidates.json"
DOWNLOAD_LOG_CSV = DISCOVERY_OUTPUT_DIR / "model_download_log.csv"
TRAIN_LOG_CSV = DISCOVERY_OUTPUT_DIR / "model_train_log.csv"
ERRORS_CSV = DISCOVERY_OUTPUT_DIR / "errors.csv"
REPORT_MD = DISCOVERY_OUTPUT_DIR / "model_discovery_report.md"


def ensure_output_dirs() -> None:
    DISCOVERY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (Path("external_repos")).mkdir(parents=True, exist_ok=True)
    (Path("models") / "external_zoo").mkdir(parents=True, exist_ok=True)


def dedupe_candidates(candidates: Iterable[ModelCandidate]) -> list[ModelCandidate]:
    seen: dict[str, ModelCandidate] = {}
    for candidate in candidates:
        candidate = normalize_candidate(candidate)
        keys = [
            candidate.candidate_id.strip().lower(),
            candidate.github_url.strip().lower(),
            candidate.hf_url.strip().lower(),
            candidate.source_url.strip().lower(),
        ]
        key = next((item for item in keys if item), candidate.model_name.strip().lower())
        if key not in seen:
            seen[key] = candidate
            continue

        existing = seen[key]
        if candidate.priority < existing.priority:
            seen[key] = candidate
        else:
            merged_notes = " | ".join(
                item for item in [existing.notes, candidate.notes] if item
            )
            existing.notes = merged_notes[:1200]
    return sorted(seen.values(), key=lambda c: (c.priority, c.model_name.lower()))


def save_candidates(candidates: list[ModelCandidate]) -> None:
    ensure_output_dirs()
    rows = [candidate.to_row() for candidate in candidates]

    with CANDIDATES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    CANDIDATES_JSON.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_log(path: Path, row: dict) -> None:
    ensure_output_dirs()
    exists = path.exists()
    fields = list(row.keys())
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def write_report(candidates: list[ModelCandidate], errors: list[dict] | None = None) -> None:
    ensure_output_dirs()
    errors = errors or []
    total = len(candidates)
    by_category = {}
    for candidate in candidates:
        by_category[candidate.category] = by_category.get(candidate.category, 0) + 1

    lines = [
        "# Model Discovery Report",
        "",
        "本报告只用于机器学习模型调研和项目展示，不构成投资建议。",
        "",
        f"- candidates: {total}",
        f"- category_counts: {by_category}",
        f"- errors: {len(errors)}",
        "",
        "## Top Priority Candidates",
        "",
        "| priority | category | model | source | pretrained | training_code | notes |",
        "|---:|---|---|---|---|---|---|",
    ]
    for candidate in candidates[:30]:
        lines.append(
            "| {priority} | {category} | {name} | {source} | {pretrained} | {training} | {notes} |".format(
                priority=candidate.priority,
                category=candidate.category,
                name=candidate.model_name.replace("|", "/"),
                source=(candidate.source_url or "").replace("|", "/"),
                pretrained="Y" if candidate.has_pretrained_weight else "N",
                training="Y" if candidate.has_training_code else "N",
                notes=(candidate.notes or "").replace("\n", " ").replace("|", "/")[:180],
            )
        )

    if errors:
        lines.extend(["", "## Search Errors", ""])
        for error in errors:
            lines.append(f"- {error.get('source', 'unknown')}: {error.get('error', '')}")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def save_errors(errors: list[dict]) -> None:
    ensure_output_dirs()
    if not errors:
        if not ERRORS_CSV.exists():
            ERRORS_CSV.write_text("source,error\n", encoding="utf-8-sig")
        return

    fields = sorted({key for row in errors for key in row.keys()})
    with ERRORS_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(errors)

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.executor import run_agent_request


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        rows.append(value)
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def _tool_names(result: dict[str, Any]) -> list[str]:
    return [
        str(item.get("tool_name") or "")
        for item in (result.get("tool_calls") or [])
        if isinstance(item, dict) and item.get("tool_name")
    ]


def _cited_chunk_ids(result: dict[str, Any], *, answer: str = "") -> list[str]:
    found: list[str] = []
    for call in result.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        payload = call.get("result") or call.get("output") or call.get("data") or {}
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for chunk in data.get("chunks") or data.get("records") or []:
            if isinstance(chunk, dict) and chunk.get("chunk_id"):
                found.append(str(chunk["chunk_id"]))
    found.extend(re.findall(r"\[(chunk_[A-Za-z0-9_-]+)\]", answer))
    return list(dict.fromkeys(found))


def _validate_production_result(case_id: str, result: dict[str, Any], answer: str) -> None:
    rag_calls = [
        item
        for item in (result.get("tool_calls") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or "") == "stock_rag"
    ]
    failed_calls = [item for item in rag_calls if not bool(item.get("success"))]
    if failed_calls:
        error_types = sorted(
            {
                str((item.get("runtime_reliability") or {}).get("error_type") or "tool_failed")
                for item in failed_calls
            }
        )
        raise RuntimeError(f"{case_id}: stock_rag tool failed: {','.join(error_types)}")
    invalid_markers = ("runtime_timeout", "runtimetimeouterror", "traceback (most recent call last)")
    lowered = answer.lower()
    if any(marker in lowered for marker in invalid_markers):
        raise RuntimeError(f"{case_id}: production Agent returned a runtime error instead of an answer")


def capture_rows(
    rows: list[dict[str, Any]],
    *,
    output_path: Path,
    user_id: str,
    force: bool = False,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    for index, source_row in enumerate(rows, start=1):
        row = dict(source_row)
        if row.get("actual_response") and not force:
            captured.append(row)
            continue
        case_id = str(row.get("case_id") or f"case_{index:03d}")
        query = str(row.get("user_input") or "").strip()
        if not query:
            raise ValueError(f"{case_id}: user_input is empty")
        result = run_agent_request(
            query,
            user_id=user_id,
            session_id=f"ragas_capture_{case_id}",
            top_k=10,
        )
        names = _tool_names(result)
        if result.get("pending_approval") or result.get("requires_confirmation"):
            raise RuntimeError(f"{case_id}: capture unexpectedly entered a protected write flow")
        if str(result.get("intent") or "") != "stock_rag" or "stock_rag" not in names:
            raise RuntimeError(
                f"{case_id}: production response did not use stock_rag; "
                f"intent={result.get('intent')} tools={names}"
            )
        answer = str(result.get("answer") or "").strip()
        if not answer:
            raise RuntimeError(f"{case_id}: production Agent returned an empty answer")
        _validate_production_result(case_id, result, answer)
        metadata = dict(row.get("metadata") or {})
        metadata.update(
            {
                "response_cited_chunk_ids": _cited_chunk_ids(result, answer=answer),
                "response_model": str((result.get("runtime") or {}).get("report_model") or "production_agent_runtime"),
                "response_prompt_version": "run_agent_request",
                "response_tool_names": names,
            }
        )
        row.update(
            {
                "actual_response": answer,
                "response_run_id": str(result.get("run_id") or ""),
                "response_source": "production_agent_runtime",
                "metadata": metadata,
            }
        )
        captured.append(row)
        _write_rows(output_path, captured + rows[index:])
        print(f"captured {index}/{len(rows)} {case_id} run_id={row['response_run_id']}", flush=True)
    _write_rows(output_path, captured)
    return captured


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture actual production Agent responses for a Ragas dataset.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--user-id", default="ragas_eval_readonly")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-id", default="")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    rows = _read_rows(dataset_path)
    if args.case_id:
        rows = [row for row in rows if str(row.get("case_id") or "") == str(args.case_id)]
    if args.limit is not None:
        rows = rows[: max(0, int(args.limit))]
    if not rows:
        raise ValueError("no evaluation cases matched the requested selection")
    if output_path.exists() and not args.force:
        existing = {
            str(row.get("case_id") or ""): row
            for row in _read_rows(output_path)
            if row.get("actual_response")
        }
        rows = [dict(existing.get(str(row.get("case_id") or ""), row)) for row in rows]
    capture_rows(
        rows,
        output_path=output_path,
        user_id=str(args.user_id),
        force=bool(args.force),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

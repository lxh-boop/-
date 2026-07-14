from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .critic_sanitizer import CriticSanitizer
from .critic_types import CriticResult


class ReflectionStore:
    def __init__(self, *, output_dir: str | Path = "outputs", sanitizer: CriticSanitizer | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.sanitizer = sanitizer or CriticSanitizer()

    def save_result(self, result: CriticResult | dict[str, Any], *, user_id: str = "default") -> dict[str, Any]:
        safe = self.sanitizer.sanitize_for_audit(result)
        run_id = str(safe.get("run_id") or "no_run")
        path = self._path_for(user_id=user_id, run_id=run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if str(safe.get("critic_id") or "") in self._critic_ids(path):
            return safe
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "critic_result", "critic_result": safe}, ensure_ascii=False) + "\n")
        return safe

    def list_results_by_run(self, run_id: str, *, user_id: str = "default") -> list[CriticResult]:
        results: list[CriticResult] = []
        for record in self._read_records(self._path_for(user_id=user_id, run_id=run_id)):
            payload = record.get("critic_result") if record.get("kind") == "critic_result" else None
            if isinstance(payload, dict):
                try:
                    results.append(CriticResult.from_dict(payload))
                except Exception:
                    continue
        return results

    def _path_for(self, *, user_id: str, run_id: str) -> Path:
        return self.output_dir / "reflection_logs" / _safe_path_part(user_id or "default") / f"{_safe_path_part(run_id or 'no_run')}.jsonl"

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    @staticmethod
    def _critic_ids(path: Path) -> set[str]:
        return {
            str((record.get("critic_result") or {}).get("critic_id") or "")
            for record in ReflectionStore._read_records(path)
            if isinstance(record.get("critic_result"), dict)
        }


def _safe_path_part(value: str) -> str:
    text = str(value or "default")
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)[:120] or "default"

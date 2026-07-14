from __future__ import annotations

import json
from pathlib import Path

from evaluation.agent_harness.schemas import HarnessCase


def load_cases(path: str | Path) -> list[HarnessCase]:
    case_path = Path(path)
    cases: list[HarnessCase] = []
    if not case_path.exists():
        raise FileNotFoundError(f"agent harness case file not found: {case_path}")
    for line_number, line in enumerate(case_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        payload = json.loads(text)
        case = HarnessCase.from_mapping(payload)
        if not case.case_id:
            raise ValueError(f"case_id is required at {case_path}:{line_number}")
        if not case.query:
            raise ValueError(f"query is required at {case_path}:{line_number}")
        cases.append(case)
    return cases

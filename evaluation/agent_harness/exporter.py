from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.agent_harness.schemas import HarnessCaseResult


def export_report(
    *,
    output_dir: str | Path,
    config: dict[str, Any],
    metrics: dict[str, Any],
    results: list[HarnessCaseResult],
) -> Path:
    report_dir = Path(output_dir) / "evaluation" / "agent_harness"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"agent_harness_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "config": config,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "results": [result.to_dict() for result in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path

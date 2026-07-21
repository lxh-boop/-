from __future__ import annotations

import json
from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_strategy_preview_contains_config_and_code_diff(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {"target_invested_weight": 0.70},
        },
    )
    preview = json.loads(
        (
            Path(result.data["artifact_root"])
            / "implementation_preview.json"
        ).read_text(encoding="utf-8")
    )

    assert preview["config_diff"]["target_invested_weight"] == {
        "before": 0.8,
        "after": 0.7,
    }
    assert "planned_add" in preview["code_diff_summary"]
    assert preview["formal_files_planned"]

from __future__ import annotations

import json
from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_strategy_backtest_uses_same_inputs_for_baseline_and_candidate(
    tmp_path,
) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {"min_rebalance_weight_delta": 0.03},
        },
    )
    report = json.loads(
        (
            Path(result.data["artifact_root"])
            / "backtest_report.json"
        ).read_text(encoding="utf-8")
    )

    assert report["baseline_input_hash"] == report["candidate_input_hash"]
    assert report["input_hash"] == report["baseline_input_hash"]
    assert report["inputs"]["fee_rate"] == 0.0003
    assert len(report["inputs"]["dates"]) == len(
        report["inputs"]["market_returns"]
    )

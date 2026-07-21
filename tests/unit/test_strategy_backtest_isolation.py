from __future__ import annotations

import json
from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_strategy_backtest_isolation_flags_no_formal_writes(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {
                "entry_top_k": 8,
                "hold_buffer_rank": 14,
                "max_positions": 8,
                "target_invested_weight": 0.70,
                "minimum_cash_ratio": 0.15,
            },
        },
    )
    report = json.loads(
        (
            Path(result.data["artifact_root"])
            / "backtest_report.json"
        ).read_text(encoding="utf-8")
    )

    assert result.success
    assert report["status"] == "passed"
    assert report["isolation"]["uses_temporary_account"] is True
    assert report["isolation"]["writes_formal_account"] is False
    assert report["isolation"]["writes_formal_outputs"] is False

from __future__ import annotations

import json
from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_strategy_preview_contains_risk_return_tradeoffs_and_rollback(
    tmp_path,
) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {
                "target_invested_weight": 0.65,
                "minimum_cash_ratio": 0.20,
                "min_rebalance_weight_delta": 0.03,
            },
        },
    )
    preview = json.loads(
        (
            Path(result.data["artifact_root"])
            / "implementation_preview.json"
        ).read_text(encoding="utf-8")
    )

    metrics = {
        item["metric"] for item in preview["risk_return_tradeoffs"]
    }
    assert {
        "annualized_return",
        "max_drawdown",
        "volatility",
        "turnover",
        "average_cash_ratio",
        "concentration",
        "executability_rate",
    } <= metrics
    assert preview["rollback_plan"]["preserve_history"] is True
    assert preview["affects_current_positions"] is False

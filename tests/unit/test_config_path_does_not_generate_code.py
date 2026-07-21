from __future__ import annotations

from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_config_path_does_not_generate_python_code(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {
                "entry_top_k": 8,
                "hold_buffer_rank": 14,
                "max_positions": 8,
                "target_invested_weight": 0.72,
                "minimum_cash_ratio": 0.12,
                "min_rebalance_weight_delta": 0.02,
            },
        },
    )

    root = Path(result.data["artifact_root"])
    assert result.success
    assert result.data["implementation_type"] == "config"
    assert list((root / "generated_code").rglob("*.py")) == []
    assert (root / "generated_config.json").exists()

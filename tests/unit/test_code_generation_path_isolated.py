from __future__ import annotations

from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_code_generation_path_is_isolated_and_user_scoped(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "code",
            "new_capability_spec": {
                "name": "dynamic_market_exposure_control",
                "inputs": ["market_regime", "ranking"],
                "output": "target_portfolio",
            },
        },
    )

    root = Path(result.data["artifact_root"])
    assert result.success
    assert "u1" in root.parts
    assert root.is_relative_to(
        (tmp_path / "runtime" / "strategy_drafts").resolve()
    )
    assert (root / "generated_code" / "strategy_plugin.py").exists()

from __future__ import annotations

from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_generated_code_cannot_bypass_write_gateway(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "code",
            "new_capability_spec": {"name": "market_regime_filter"},
        },
    )
    source = (
        Path(result.data["artifact_root"])
        / "generated_code"
        / "strategy_plugin.py"
    ).read_text(encoding="utf-8")

    assert result.success
    assert "WriteGateway" not in source
    assert "execute_confirmed_plan" not in source
    assert "confirmation_token" not in source

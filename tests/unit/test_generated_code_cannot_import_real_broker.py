from __future__ import annotations

from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_generated_code_cannot_import_real_broker(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "code",
            "new_capability_spec": {
                "name": "paper_only_dynamic_exposure",
                "broker": "must_not_be_used",
            },
        },
    )
    source = (
        Path(result.data["artifact_root"])
        / "generated_code"
        / "strategy_plugin.py"
    ).read_text(encoding="utf-8")

    assert result.success
    assert "ccxt" not in source
    assert "easytrader" not in source
    assert "requests" not in source
    assert "broker" not in source.lower()

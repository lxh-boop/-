from __future__ import annotations

from pathlib import Path

from strategy_workflow_test_utils import prepare_proposal


def test_composite_path_is_written_only_to_isolated_runtime(tmp_path) -> None:
    _, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "composite",
            "components": [
                {"name": "hierarchical_top10"},
                {"name": "turnover_filter"},
            ],
            "config": {"entry_top_k": 10},
        },
    )

    root = Path(result.data["artifact_root"])
    allowed = (tmp_path / "runtime" / "strategy_drafts").resolve()
    assert result.success
    assert allowed in root.resolve().parents
    assert (root / "generated_code" / "composition.json").exists()

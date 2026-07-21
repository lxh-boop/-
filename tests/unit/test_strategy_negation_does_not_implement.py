from __future__ import annotations

from strategy_workflow_test_utils import save_draft


def test_strategy_negation_does_not_enter_implementation(tmp_path) -> None:
    first = save_draft(tmp_path)
    result = save_draft(
        tmp_path,
        proposal_json={},
        feedback="先不要实施",
        action="continue_discussion",
        proposal_id=first.data["proposal"]["proposal_id"],
    )

    assert result.success
    assert result.data["implementation_requested"] is False
    assert result.data["registry_changed"] is False
    assert result.data["binding_changed"] is False
    assert result.data["positions_changed"] is False

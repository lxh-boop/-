from __future__ import annotations

from strategy_workflow_test_utils import save_draft


def test_strategy_proposal_revision_updates_same_proposal(tmp_path) -> None:
    first = save_draft(tmp_path)
    second = save_draft(
        tmp_path,
        proposal_json={
            "config": {"entry_top_k": 10, "target_invested_weight": 0.70}
        },
        feedback="现金再多一点",
    )

    assert second.data["proposal"]["proposal_id"] == first.data["proposal"]["proposal_id"]
    assert second.data["proposal"]["current_version"] == 2
    assert second.data["proposal"]["status"] == "revising"
    assert second.data["proposal_version"]["user_feedback"] == "现金再多一点"

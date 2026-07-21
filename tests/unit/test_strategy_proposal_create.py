from __future__ import annotations

from strategy_workflow_test_utils import proposal_service, save_draft


def test_strategy_proposal_create_is_draft_without_formal_write(tmp_path) -> None:
    result = save_draft(tmp_path)
    proposal = result.data["proposal"]
    version = result.data["proposal_version"]

    assert result.success
    assert result.requires_confirmation is False
    assert proposal["status"] == "draft"
    assert proposal["current_version"] == 1
    assert version["version"] == 1
    assert result.data["formal_write_created"] is False
    assert proposal_service(tmp_path).get(
        proposal["proposal_id"],
        user_id="u1",
    ) is not None

from __future__ import annotations

from strategy_workflow_test_utils import proposal_service, save_draft


def test_strategy_proposal_version_history_is_append_only(tmp_path) -> None:
    first = save_draft(tmp_path)
    save_draft(
        tmp_path,
        proposal_json={"config": {"entry_top_k": 12}},
        feedback="不要减少持股数量",
    )
    versions = proposal_service(tmp_path).list_versions(
        first.data["proposal"]["proposal_id"],
        user_id="u1",
    )

    assert [item.version for item in versions] == [1, 2]
    assert versions[0].proposal_json["config"]["entry_top_k"] == 10
    assert versions[1].proposal_json["config"]["entry_top_k"] == 12

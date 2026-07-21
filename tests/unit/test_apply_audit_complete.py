from __future__ import annotations

from agent.write_gateway import execute_confirmed_plan_v2
from database.repositories import AgentRepository
from strategy_apply_test_utils import apply_plan
from strategy_workflow_test_utils import database_path


def test_apply_audit_contains_proposal_approval_commit_and_action(
    tmp_path,
) -> None:
    _, _, plan = apply_plan(tmp_path)
    result = execute_confirmed_plan_v2(
        plan.data["plan_id"],
        plan.data["confirmation_token"],
        "u1",
        conversation_id="conv_1",
        run_id="run_gateway",
        db_path=database_path(tmp_path),
        output_dir=tmp_path / "outputs",
    )
    repo = AgentRepository(database_path(tmp_path))

    assert result.success
    assert repo.get_action_proposal(plan.data["plan_id"])["status"] == "executed"
    assert repo.store.list(
        "action_approvals",
        {"plan_id": plan.data["plan_id"]},
    )
    commits = repo.store.list(
        "action_commits",
        {"plan_id": plan.data["plan_id"]},
    )
    assert len(commits) == 1
    assert commits[0]["status"] == "executed"
    actions = repo.store.list(
        "agent_action_log",
        {"plan_id": plan.data["plan_id"]},
    )
    assert any(
        row["intent"] == "apply_strategy_implementation"
        for row in actions
    )

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from agent.agent_specs import RISK_OPERATION, validate_tool_allowed
from agent.executor import run_agent_request
from agent.runtime import load_run_snapshot
from database.repositories.agent_repository import AgentRepository
from portfolio.storage import PortfolioStorage
from agent_control_center_utils import write_agent_fixture


@pytest.fixture(autouse=True)
def _fixed_agent_trade_date(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 6, 12, 9, 30, 0)
            return value if tz is None else value.replace(tzinfo=tz)

    monkeypatch.setattr("agent.tools.rebalance_plan_tool.datetime", FixedDateTime)
    monkeypatch.setattr("portfolio.paper_position.now_text", lambda: "2026-06-12 09:30:00")


def _preview_adjustment(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)
    result = run_agent_request(
        "000001 \u5356\u51fa100\u80a1",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )
    return output_dir, db_path, result


def test_phase3_readonly_analysis_creates_proposal_without_commit(tmp_path) -> None:
    output_dir, db_path, result = _preview_adjustment(tmp_path)

    assert result["success"] is True
    assert result["intent"] == "one_time_position_operation"
    assert result["runtime"]["status"] == "waiting_for_approval"
    assert result["orchestration"]["multi_agent"] is True
    assert result["orchestration"]["protected_operation"] is True
    assert result["orchestration"]["write_operations_executed"] == 0
    assert "risk_operation" in result["orchestration"]["agent_outputs"]

    plan_id = result["result"]["data"]["plan_id"]
    repo = AgentRepository(db_path)
    proposal = repo.get_action_proposal(plan_id)
    assert proposal is not None
    assert proposal["run_id"] == result["run_id"]
    assert repo.store.list("action_commits", {"plan_id": plan_id}) == []

    snapshot = load_run_snapshot(db_path, result["run_id"])
    roles = [
        (row.get("metadata_json") or {}).get("agent_role")
        for row in snapshot["steps"]
        if (row.get("metadata_json") or {}).get("agent_role")
    ]
    assert "risk_operation" in roles


def test_phase3_correct_confirmation_revalidates_commits_same_run(tmp_path) -> None:
    output_dir, db_path, preview = _preview_adjustment(tmp_path)
    data = preview["result"]["data"]

    confirmed = run_agent_request(
        f"confirm execute {data['plan_id']} token: {data['confirmation_token']}",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    assert confirmed["success"] is True
    assert confirmed["run_id"] == preview["run_id"]
    assert confirmed["runtime"]["status"] == "completed"
    repo = AgentRepository(db_path)
    approvals = repo.store.list("action_approvals", {"plan_id": data["plan_id"]})
    commits = repo.store.list("action_commits", {"plan_id": data["plan_id"]})
    assert any(row["status"] == "confirmed" for row in approvals)
    assert len(commits) == 1
    assert commits[0]["status"] == "executed"

    snapshot = load_run_snapshot(db_path, preview["run_id"])
    transitions = (snapshot["run"].get("metadata_json") or {}).get("status_transitions") or []
    transition_pairs = [(row.get("from"), row.get("to")) for row in transitions]
    assert ("waiting_for_approval", "revalidating") in transition_pairs
    assert ("revalidating", "committing") in transition_pairs
    assert ("committing", "completed") in transition_pairs
    closure = (snapshot["run"].get("metadata_json") or {}).get("approval_closure") or {}
    assert closure["plan_id"] == data["plan_id"]
    assert closure["approval_id"]
    assert closure["commit_id"]

    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    adjusted = [row for row in storage.load_positions("u1") if row.stock_code == "000001"]
    assert adjusted and adjusted[0].quantity == 900.0


def test_phase3_state_change_rejects_commit_on_revalidate(tmp_path) -> None:
    output_dir, db_path, preview = _preview_adjustment(tmp_path)
    data = preview["result"]["data"]
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    account = storage.load_account("paper_u1")
    assert account is not None
    storage.save_account(replace(account, cash=account.cash + 1.0, total_assets=account.total_assets + 1.0))

    confirmed = run_agent_request(
        f"confirm execute {data['plan_id']} token: {data['confirmation_token']}",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key="",
    )

    assert confirmed["success"] is False
    assert confirmed["run_id"] == preview["run_id"]
    assert confirmed["runtime"]["status"] == "failed"
    commits = AgentRepository(db_path).store.list("action_commits", {"plan_id": data["plan_id"]})
    assert commits == []


def test_phase3_duplicate_confirmation_is_idempotent(tmp_path) -> None:
    output_dir, db_path, preview = _preview_adjustment(tmp_path)
    data = preview["result"]["data"]
    confirm_query = f"confirm execute {data['plan_id']} token: {data['confirmation_token']}"
    first = run_agent_request(confirm_query, user_id="u1", output_dir=output_dir, db_path=db_path, llm_api_key="")
    second = run_agent_request(confirm_query, user_id="u1", output_dir=output_dir, db_path=db_path, llm_api_key="")

    assert first["success"] is True
    assert second["success"] is False
    assert "already_executed" in second["result"]["errors"]
    commits = AgentRepository(db_path).store.list("action_commits", {"plan_id": data["plan_id"]})
    assert len(commits) == 1


def test_phase3_risk_operation_cannot_execute_or_commit() -> None:
    validate_tool_allowed(RISK_OPERATION, "manual_position_operation_tool")
    with pytest.raises(PermissionError):
        validate_tool_allowed(RISK_OPERATION, "paper_trade_execute")

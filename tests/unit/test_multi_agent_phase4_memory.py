from __future__ import annotations

import pytest

from agent.memory import LayeredMemoryService
from agent.runtime import AgentRuntimeRecorder, compare_run_decisions, load_run_snapshot
from database.repositories import AgentRepository


def test_phase4_confirmed_long_term_preference_is_retrievable_across_sessions(tmp_path) -> None:
    service = LayeredMemoryService(tmp_path / "agent.db")
    record = service.remember_memory(
        user_id="u1",
        content="Prefer lower drawdown when explaining portfolio changes for 600519.",
        memory_type="preference",
        source_run_id="run_source",
        source_type="confirmed_user_preference",
        source_id="msg_confirmed",
        user_confirmed=True,
        stock_codes=["600519"],
        confidence=0.9,
        importance=0.8,
    )

    recalled = service.search_memories(
        user_id="u1",
        query="600519 drawdown preference",
        memory_type="preference",
        limit=5,
    )

    assert recalled
    assert recalled[0]["memory"]["memory_id"] == record["memory_id"]
    assert recalled[0]["memory"]["source_run_id"] == "run_source"
    assert recalled[0]["memory"]["confidence"] == 0.9


def test_phase4_one_time_instruction_does_not_become_long_term_memory(tmp_path) -> None:
    service = LayeredMemoryService(tmp_path / "agent.db")

    with pytest.raises(ValueError, match="one_time_operation_cannot_be_long_term_memory"):
        service.remember_memory(
            user_id="u1",
            content="Only this time, reduce 600519 by half.",
            memory_type="preference",
            source_run_id="run_once",
            source_type="confirmed_user_preference",
            source_id="msg_once",
            user_confirmed=True,
            metadata={"operation_scope": "one_time"},
        )

    assert service.search_memories(user_id="u1", query="600519", memory_type="preference") == []


def test_phase4_agent_inference_cannot_write_user_preference(tmp_path) -> None:
    service = LayeredMemoryService(tmp_path / "agent.db")

    with pytest.raises(ValueError, match="long_term_memory_requires_user_confirmation"):
        service.remember_memory(
            user_id="u1",
            content="Agent infers the user likes high-risk stocks.",
            memory_type="preference",
            source_run_id="run_agent",
            source_type="agent_run",
            source_id="run_agent",
            user_confirmed=False,
            metadata={"source_assertion": "agent_inference"},
        )


def test_phase4_conflicting_preference_creates_versioned_supersession(tmp_path) -> None:
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    old = service.remember_memory(
        user_id="u1",
        content="Prefer concise answers.",
        memory_type="preference",
        source_run_id="run_old",
        source_type="confirmed_user_preference",
        source_id="msg_old",
        user_confirmed=True,
    )
    new = service.remember_memory(
        user_id="u1",
        content="Prefer detailed answers with evidence.",
        memory_type="preference",
        source_run_id="run_new",
        source_type="confirmed_user_preference",
        source_id="msg_new",
        user_confirmed=True,
        supersedes_memory_id=old["memory_id"],
        change_reason="user_correction",
    )

    repo = AgentRepository(db_path)
    old_row = repo.get_memory_item(old["memory_id"])
    new_memory = service.search_memories(user_id="u1", query="detailed evidence", memory_type="preference")[0]["memory"]

    assert old_row["status"] == "superseded"
    assert new_memory["memory_id"] == new["memory_id"]
    assert new_memory["version"] == 2


def test_phase4_agent_memory_views_are_least_privilege(tmp_path) -> None:
    service = LayeredMemoryService(tmp_path / "agent.db")
    service.remember_memory(
        user_id="u1",
        content="Use conservative portfolio language.",
        memory_type="preference",
        source_run_id="run_pref",
        source_type="confirmed_user_preference",
        source_id="msg_pref",
        user_confirmed=True,
    )
    service.remember_memory(
        user_id="u1",
        content="Previous decision produced one proposal and no commit.",
        memory_type="decision",
        source_run_id="run_decision",
        source_type="agent_run",
        source_id="run_decision",
    )

    market_view = service.memory_view_for_agent(
        user_id="u1",
        query="portfolio language decision",
        agent_role="market_intelligence",
    )
    portfolio_view = service.memory_view_for_agent(
        user_id="u1",
        query="portfolio language decision",
        agent_role="portfolio_analysis",
    )

    assert "preference" not in market_view["allowed_memory_types"]
    assert all(row["memory"]["memory_type"] != "preference" for row in market_view["items"])
    assert "preference" in portfolio_view["allowed_memory_types"]
    assert any(row["memory"]["memory_type"] == "preference" for row in portfolio_view["items"])


def test_phase4_decision_replay_includes_memory_handoff_proposal_approval_commit(tmp_path) -> None:
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    memory = service.remember_memory(
        user_id="u1",
        content="Prefer no automatic position changes.",
        memory_type="preference",
        source_run_id="run_pref",
        source_type="confirmed_user_preference",
        source_id="msg_pref",
        user_confirmed=True,
    )
    runtime = AgentRuntimeRecorder(user_id="u1", goal="adjust 000001", db_path=db_path, session_id="s1")
    runtime.merge_metadata(
        {
            "memory_used": {
                "pre_execution": [
                    {
                        "memory_id": memory["memory_id"],
                        "memory_type": "preference",
                        "version": 1,
                        "source_run_id": "run_pref",
                    }
                ]
            }
        }
    )
    runtime.create_step(
        "agent_portfolio",
        "portfolio_analysis",
        metadata={
            "agent_role": "portfolio_analysis",
            "handoff_from": "market_intelligence",
            "handoff_to": "risk_operation",
        },
    )
    repo = AgentRepository(db_path)
    repo.upsert_action_proposal(
        {
            "plan_id": "agent_plan_1",
            "user_id": "u1",
            "run_id": runtime.run_id,
            "operation_type": "execute_adjust_position",
            "plan_hash": "hash_1",
            "status": "pending",
            "proposed_changes": [{"stock_code": "000001", "quantity_delta": -100}],
        }
    )
    repo.upsert_action_approval(
        {
            "approval_id": "approval_1",
            "plan_id": "agent_plan_1",
            "user_id": "u1",
            "plan_hash": "hash_1",
            "status": "approved",
        }
    )
    repo.upsert_action_commit(
        {
            "commit_id": "commit_1",
            "plan_id": "agent_plan_1",
            "approval_id": "approval_1",
            "user_id": "u1",
            "status": "executed",
            "idempotency_key": "idem_1",
        }
    )

    replay = load_run_snapshot(db_path, runtime.run_id)["decision_replay"]

    assert replay["used_memories"][0]["memory_id"] == memory["memory_id"]
    assert replay["agent_handoffs"][0]["handoff_to"] == "risk_operation"
    assert replay["proposals"][0]["plan_id"] == "agent_plan_1"
    assert replay["approvals"][0]["approval_id"] == "approval_1"
    assert replay["commits"][0]["commit_id"] == "commit_1"


def test_phase4_delete_memory_updates_retrieval_and_sensitive_fields_are_redacted(tmp_path) -> None:
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    record = service.remember_memory(
        user_id="u1",
        content="token: should_not_persist; prefer risk summaries.",
        memory_type="preference",
        source_run_id="run_sensitive",
        source_type="confirmed_user_preference",
        source_id="msg_sensitive",
        user_confirmed=True,
        metadata={"api_key": "secret", "nested": {"confirmation_token": "abc"}},
    )
    stored = AgentRepository(db_path).get_memory_item(record["memory_id"])
    assert "should_not_persist" not in stored["content"]
    assert stored["metadata_json"]["api_key"] == "***"
    assert stored["metadata_json"]["nested"]["confirmation_token"] == "***"

    assert service.delete_memory(user_id="u1", memory_id=record["memory_id"], reason="user_deleted")
    assert service.search_memories(user_id="u1", query="risk summaries", memory_type="preference") == []


def test_phase4_decision_compare_reports_differences(tmp_path) -> None:
    db_path = tmp_path / "agent.db"
    left = AgentRuntimeRecorder(user_id="u1", goal="left", db_path=db_path)
    right = AgentRuntimeRecorder(user_id="u1", goal="right", db_path=db_path)
    repo = AgentRepository(db_path)
    repo.upsert_action_proposal(
        {
            "plan_id": "agent_plan_left",
            "user_id": "u1",
            "run_id": left.run_id,
            "operation_type": "execute_adjust_position",
            "plan_hash": "hash_left",
            "status": "pending",
        }
    )
    repo.upsert_action_proposal(
        {
            "plan_id": "agent_plan_right",
            "user_id": "u1",
            "run_id": right.run_id,
            "operation_type": "execute_adjust_position",
            "plan_hash": "hash_right",
            "status": "pending",
        }
    )

    diff = compare_run_decisions(db_path, left.run_id, right.run_id)

    assert diff["differences"]["proposal_only_left"] == ["agent_plan_left"]
    assert diff["differences"]["proposal_only_right"] == ["agent_plan_right"]

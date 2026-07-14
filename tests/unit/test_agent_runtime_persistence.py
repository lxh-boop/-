from __future__ import annotations

import sqlite3

from database.connection import initialize_database
from database.repositories.agent_repository import AgentRepository
from agent.runtime import AgentRuntimeRecorder, load_run_snapshot


PHASE_38_TABLES = {
    "conversations",
    "messages",
    "agent_runs",
    "agent_steps",
    "agent_tool_calls",
    "agent_sources",
    "agent_sandbox_runs",
    "action_proposals",
    "action_approvals",
    "action_commits",
    "conversation_summaries",
    "memory_items",
    "memory_links",
    "user_feedback",
    "artifacts",
}


def test_phase_38_runtime_tables_are_created(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

    table_names = {row[0] for row in rows}
    assert PHASE_38_TABLES.issubset(table_names)


def test_agent_runtime_repository_round_trip_and_user_isolation(tmp_path) -> None:
    repo = AgentRepository(tmp_path / "agent_quant.db")

    repo.upsert_conversation(
        {
            "conversation_id": "conv_1",
            "user_id": "u1",
            "title": "runtime test",
            "status": "active",
            "metadata": {"topic": "agent"},
        }
    )
    repo.upsert_conversation(
        {
            "conversation_id": "conv_2",
            "user_id": "u2",
            "title": "other user",
            "status": "active",
        }
    )
    repo.upsert_message(
        {
            "message_id": "msg_1",
            "conversation_id": "conv_1",
            "user_id": "u1",
            "role": "user",
            "content": "查看组合风险",
            "metadata": {"language": "zh"},
        }
    )
    repo.upsert_agent_run(
        {
            "run_id": "run_1",
            "conversation_id": "conv_1",
            "user_id": "u1",
            "goal": "risk review",
            "status": "completed",
            "metadata": {"limits": {"max_steps": 12}},
        }
    )
    repo.upsert_agent_step(
        {
            "step_id": "step_1",
            "run_id": "run_1",
            "intent": "portfolio_risk",
            "status": "succeeded",
            "depends_on": [],
            "tool_args_summary": {"user_id": "u1"},
        }
    )
    repo.upsert_agent_tool_call(
        {
            "tool_call_id": "call_1",
            "run_id": "run_1",
            "step_id": "step_1",
            "user_id": "u1",
            "tool_name": "portfolio_risk",
            "status": "success",
            "input_summary": {"user_id": "u1"},
            "output_summary": {"success": True},
        }
    )
    repo.upsert_agent_source(
        {
            "source_id": "src_1",
            "run_id": "run_1",
            "tool_call_id": "call_1",
            "user_id": "u1",
            "source_type": "database",
            "source_title": "paper_account_snapshot",
            "database_record_id": "snapshot_1",
            "snippet": "risk snapshot",
        }
    )
    repo.upsert_agent_sandbox_run(
        {
            "sandbox_run_id": "sandbox_1",
            "run_id": "run_1",
            "step_id": "step_1",
            "user_id": "u1",
            "snapshot_id": "snap_1",
            "code_hash": "abc",
            "status": "succeeded",
            "result_summary": {"rows": 3},
            "generated_files": [],
        }
    )
    repo.upsert_action_proposal(
        {
            "plan_id": "plan_1",
            "user_id": "u1",
            "run_id": "run_1",
            "operation_type": "paper_order",
            "snapshot_id": "snap_1",
            "business_state_version": "v1",
            "plan_hash": "hash_1",
            "status": "pending",
            "before_state_summary": {"cash": 1000},
            "proposed_changes": [{"type": "buy"}],
            "after_state_preview": {"cash": 900},
            "warnings": ["paper only"],
            "validation_results": {"ok": True},
        }
    )
    repo.upsert_action_approval(
        {
            "approval_id": "approval_1",
            "plan_id": "plan_1",
            "user_id": "u1",
            "plan_hash": "hash_1",
            "status": "pending",
        }
    )
    repo.upsert_action_commit(
        {
            "commit_id": "commit_1",
            "plan_id": "plan_1",
            "approval_id": "approval_1",
            "user_id": "u1",
            "status": "executed",
            "idempotency_key": "plan_1_once",
            "result_summary": {"orders": 1},
        }
    )
    repo.upsert_conversation_summary(
        {
            "summary_id": "summary_1",
            "conversation_id": "conv_1",
            "user_id": "u1",
            "summary_text": "用户在查看组合风险。",
            "metadata": {"covered": ["msg_1"]},
        }
    )
    repo.upsert_memory_item(
        {
            "memory_id": "mem_1",
            "user_id": "u1",
            "conversation_id": "conv_1",
            "memory_type": "long_term_preference",
            "content": "用户偏好中文回答。",
            "topics": ["language"],
            "stock_codes": [],
            "importance": 0.8,
        }
    )
    repo.upsert_memory_link(
        {
            "link_id": "mlink_1",
            "memory_id": "mem_1",
            "linked_type": "conversation",
            "linked_id": "conv_1",
        }
    )
    repo.upsert_user_feedback(
        {
            "feedback_id": "fb_1",
            "user_id": "u1",
            "conversation_id": "conv_1",
            "run_id": "run_1",
            "feedback_type": "helpful",
            "rating": 1,
            "metadata": {"surface": "ai_agent"},
        }
    )
    repo.upsert_artifact(
        {
            "artifact_id": "artifact_1",
            "user_id": "u1",
            "run_id": "run_1",
            "artifact_type": "csv",
            "path": "outputs/example.csv",
            "content_hash": "hash_csv",
            "size_bytes": 12,
        }
    )

    conversations = repo.list_conversations("u1")
    assert [row["conversation_id"] for row in conversations] == ["conv_1"]
    assert conversations[0]["metadata_json"] == {"topic": "agent"}
    assert repo.list_messages("conv_1")[0]["metadata_json"] == {"language": "zh"}

    proposal = repo.get_action_proposal("plan_1")
    assert proposal is not None
    assert proposal["before_state_summary_json"] == {"cash": 1000}
    assert proposal["proposed_changes_json"] == [{"type": "buy"}]

    memories = repo.list_memory_items("u1", memory_type="long_term_preference")
    assert memories[0]["topics_json"] == ["language"]
    assert repo.list_memory_items("u2") == []

    feedback = repo.list_user_feedback("u1", feedback_type="helpful")
    assert feedback[0]["metadata_json"] == {"surface": "ai_agent"}
    assert repo.list_user_feedback("u2") == []

    sources = repo.list_agent_sources("u1", run_id="run_1")
    assert sources[0]["source_title"] == "paper_account_snapshot"


def test_agent_steps_are_scoped_by_run_id_and_logical_step_id(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)
    run_ids: list[str] = []

    for index in range(3):
        runtime = AgentRuntimeRecorder(
            user_id="u1",
            goal=f"runtime collision test {index}",
            db_path=db_path,
        )
        run_ids.append(runtime.run_id)
        runtime.create_step("task_1", "portfolio_state")
        runtime.record_step_result(
            "task_1",
            {
                "success": True,
                "intent": "portfolio_state",
                "message": f"portfolio state {index}",
            },
        )
        runtime.create_step("task_2", "portfolio_risk")
        runtime.record_step_result(
            "task_2",
            {
                "success": True,
                "intent": "portfolio_risk",
                "message": f"portfolio risk {index}",
            },
        )

    with sqlite3.connect(db_path) as conn:
        step_count = conn.execute("SELECT COUNT(*) FROM agent_steps").fetchone()[0]
        distinct_runs = conn.execute("SELECT COUNT(DISTINCT run_id) FROM agent_steps").fetchone()[0]
        duplicate_records = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT step_record_id
                FROM agent_steps
                GROUP BY step_record_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

    assert step_count == 6
    assert distinct_runs == 3
    assert duplicate_records == 0

    for index, run_id in enumerate(run_ids):
        snapshot = load_run_snapshot(db_path, run_id)
        summaries = {row["step_id"]: row["observation_summary"] for row in snapshot["steps"]}
        assert summaries == {
            "task_1": f"portfolio state {index}",
            "task_2": f"portfolio risk {index}",
        }

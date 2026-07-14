from __future__ import annotations

from datetime import datetime, timedelta

from agent.runtime import AgentRuntimeRecorder
from agent.session.pending_action_store import save_pending_plan, update_pending_plan
from app.pages import ai_agent
from app.pages.ai_agent import (
    _load_conversation_messages,
    _pending_plans_for_conversation,
    _phase8_developer_details_enabled,
    _phase8_perf_state,
    _phase8_record_rerun,
    _phase8_rerun,
    _phase51_render_developer_details,
    st,
)
from database.repositories.agent_repository import AgentRepository


def _reset_state() -> None:
    try:
        st.session_state.clear()
    except Exception:
        st.session_state = {}


def _seed_conversation(repo: AgentRepository, user_id: str, conversation_id: str, message_count: int = 0) -> None:
    now = datetime(2026, 7, 3, 9, 0, 0)
    repo.upsert_conversation(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": conversation_id,
            "status": "active",
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    for index in range(message_count):
        created_at = (now + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")
        repo.upsert_message(
            {
                "message_id": f"msg_{conversation_id}_{index:03d}",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": "user",
                "content": f"{user_id} message {index:03d}",
                "language": "zh",
                "created_at": created_at,
                "metadata": {},
            }
        )


def test_phase8_message_cache_is_user_conversation_scoped_and_recent_50(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    repo = AgentRepository(db_path)
    _seed_conversation(repo, "u1", "conv_u1", message_count=60)
    _seed_conversation(repo, "u2", "conv_u2", message_count=60)

    loaded = _load_conversation_messages("u1", "conv_u1", db_path, language="zh")

    assert len(loaded) == 50
    assert loaded[0]["content"] == "u1 message 010"
    assert loaded[-1]["content"] == "u1 message 059"
    assert "u2 message" not in str(loaded)


def test_phase8_pending_plan_filter_uses_batch_run_lookup(tmp_path, monkeypatch) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    output_dir = str(tmp_path / "outputs")
    repo = AgentRepository(db_path)
    _seed_conversation(repo, "u1", "conv_a")
    _seed_conversation(repo, "u1", "conv_b")
    run_a = AgentRuntimeRecorder(user_id="u1", goal="a", db_path=db_path, session_id="conv_a")
    run_b = AgentRuntimeRecorder(user_id="u1", goal="b", db_path=db_path, session_id="conv_b")
    calls = {"batch": 0}
    original = repo.list_agent_runs_by_ids

    def counted(run_ids: list[str]):
        calls["batch"] += 1
        return original(run_ids)

    repo.list_agent_runs_by_ids = counted  # type: ignore[method-assign]
    monkeypatch.setattr(ai_agent, "_get_agent_repository", lambda _: repo)

    for plan_id, run_id in [("plan_a", run_a.run_id), ("plan_b", run_b.run_id)]:
        save_pending_plan(
            "u1",
            {
                "plan_id": plan_id,
                "run_id": run_id,
                "intent": "execute_adjust_position",
                "operation_type": "execute_adjust_position",
                "confirmation_status": "pending",
                "execution_status": "pending",
            },
            output_dir=output_dir,
        )

    plans = _pending_plans_for_conversation("u1", output_dir, db_path, "conv_a")

    assert [plan["plan_id"] for plan in plans] == ["plan_a"]
    assert calls["batch"] == 1


def test_phase8_pending_plan_status_is_not_stale_after_cancel(tmp_path) -> None:
    _reset_state()
    db_path = str(tmp_path / "agent.db")
    output_dir = str(tmp_path / "outputs")
    repo = AgentRepository(db_path)
    _seed_conversation(repo, "u1", "conv_a")
    run = AgentRuntimeRecorder(user_id="u1", goal="a", db_path=db_path, session_id="conv_a")
    save_pending_plan(
        "u1",
        {
            "plan_id": "plan_a",
            "run_id": run.run_id,
            "intent": "execute_adjust_position",
            "operation_type": "execute_adjust_position",
            "confirmation_status": "pending",
            "execution_status": "pending",
        },
        output_dir=output_dir,
    )
    assert _pending_plans_for_conversation("u1", output_dir, db_path, "conv_a")

    update_pending_plan("u1", "plan_a", {"execution_status": "cancelled"}, output_dir=output_dir)

    assert _pending_plans_for_conversation("u1", output_dir, db_path, "conv_a") == []


def test_phase8_developer_details_are_lazy_by_default(monkeypatch) -> None:
    _reset_state()
    assert not _phase8_developer_details_enabled("u1", "conv_a")

    def fail_tools():
        raise AssertionError("tools should not load before the developer details checkbox is enabled")

    monkeypatch.setattr(ai_agent, "_safe_tools", fail_tools)
    _phase51_render_developer_details(
        user_id="u1",
        session_id="conv_a",
        messages=[],
        tools=[],
        db_path=None,
        language="zh",
    )


def test_phase8_rerun_counter_records_one_action(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setattr(st, "rerun", lambda: None)

    _phase8_rerun("u1", "conversation_new")

    assert _phase8_perf_state("u1")["rerun_count"] == 1
    assert _phase8_perf_state("u1")["last_rerun_reason"] == "conversation_new"


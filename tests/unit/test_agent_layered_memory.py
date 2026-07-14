from __future__ import annotations

import pytest

from agent.context import build_agent_context
from agent.memory import LayeredMemoryService, MemoryWeights, score_memory
from database.repositories import AgentRepository
from agent_control_center_utils import write_agent_fixture


def test_memory_weights_must_sum_to_one():
    MemoryWeights()
    with pytest.raises(ValueError):
        MemoryWeights(semantic=0.5, recency=0.5, importance=0.5, entity=0.5)


def test_semantic_memory_user_isolation_and_entity_scoring(tmp_path):
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    service.remember_semantic_memory(
        user_id="u1",
        content="用户长期关注 600519 的白酒行业风险。",
        memory_type="long_term_preference",
        source_type="user_message",
        source_id="msg_u1",
        stock_codes=["600519"],
        importance=0.8,
    )
    service.remember_semantic_memory(
        user_id="u2",
        content="u2_secret_000002",
        memory_type="long_term_preference",
        source_type="user_message",
        source_id="msg_u2",
        stock_codes=["000002"],
        importance=1.0,
    )

    results = service.search_semantic_memory(user_id="u1", query="复盘 600519 风险", limit=5)

    assert results
    assert "600519" in results[0].record["content"]
    assert all(item.record["user_id"] == "u1" for item in results)
    assert "u2_secret_000002" not in str([item.to_dict() for item in results])
    score, parts = score_memory("600519", results[0].record)
    assert score > 0
    assert parts["entity"] == 1.0


def test_user_correction_supersedes_old_semantic_memory(tmp_path):
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    old = service.remember_semantic_memory(
        user_id="u1",
        content="用户偏好中文回复。",
        memory_type="language_preference",
        source_type="user_message",
        source_id="msg_old",
        topics=["language"],
    )

    new = service.remember_semantic_memory(
        user_id="u1",
        content="用户纠正：以后默认英文回复。",
        memory_type="language_preference",
        source_type="user_message",
        source_id="msg_new",
        topics=["language"],
        supersedes_memory_id=old["memory_id"],
    )

    repo = AgentRepository(db_path)
    old_row = repo.get_memory_item(old["memory_id"])
    new_row = repo.get_memory_item(new["memory_id"])
    assert old_row["status"] == "superseded"
    assert old_row["metadata_json"]["superseded_by"] == new["memory_id"]
    assert new_row["supersedes_memory_id"] == old["memory_id"]
    active = service.search_semantic_memory(user_id="u1", query="英文回复", limit=5)
    assert any(item.record["memory_id"] == new["memory_id"] for item in active)
    assert all(item.record["memory_id"] != old["memory_id"] for item in active)


def test_deleted_memory_is_not_recalled(tmp_path):
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    record = service.remember_semantic_memory(
        user_id="u1",
        content="delete_me_600519",
        memory_type="long_term_preference",
        source_type="user_feedback",
        source_id="fb_1",
        stock_codes=["600519"],
    )

    assert service.delete_memory(user_id="u1", memory_id=record["memory_id"], reason="user_requested")
    results = service.search_semantic_memory(user_id="u1", query="delete_me_600519", limit=5)

    assert results == []
    deleted = AgentRepository(db_path).get_memory_item(record["memory_id"])
    assert deleted["status"] == "deleted"
    assert deleted["metadata_json"]["delete_reason"] == "user_requested"


def test_expired_memory_does_not_enter_context(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)
    service = LayeredMemoryService(db_path)
    service.remember_semantic_memory(
        user_id="u1",
        content="expired_memory_600519",
        memory_type="long_term_preference",
        source_type="user_message",
        source_id="msg_expired",
        stock_codes=["600519"],
        valid_until="2000-01-01",
    )

    context = build_agent_context(
        query="复盘 600519",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        run_id="run_memory",
    )

    assert "expired_memory_600519" not in context.compressed_text


def test_one_time_operation_and_agent_inference_are_not_semantic_memory(tmp_path):
    service = LayeredMemoryService(tmp_path / "agent.db")

    with pytest.raises(ValueError):
        service.remember_semantic_memory(
            user_id="u1",
            content="这次把 600519 减半。",
            memory_type="long_term_preference",
            source_type="user_message",
            source_id="msg_once",
            metadata={"operation_scope": "one_time"},
        )

    with pytest.raises(ValueError):
        service.remember_semantic_memory(
            user_id="u1",
            content="Agent 推断用户喜欢高风险股票。",
            memory_type="risk_preference",
            source_type="agent_inference",
            source_id="run_1",
        )


def test_memory_source_traceability(tmp_path):
    db_path = tmp_path / "agent.db"
    service = LayeredMemoryService(db_path)
    record = service.remember_semantic_memory(
        user_id="u1",
        content="用户确认长期风险偏好为稳健。",
        memory_type="risk_preference",
        source_type="user_feedback",
        source_id="feedback_1",
        topics=["risk"],
        importance=0.9,
    )

    repo = AgentRepository(db_path)
    links = repo.list_memory_links(record["memory_id"])
    results = service.search_semantic_memory(user_id="u1", query="风险偏好", limit=5)

    assert links[0]["linked_type"] == "user_feedback"
    assert links[0]["linked_id"] == "feedback_1"
    assert results[0].sources
    assert results[0].record["source_type"] == "user_feedback"
    assert results[0].record["source_id"] == "feedback_1"


def test_working_and_episodic_memory_are_user_scoped(tmp_path):
    db_path = tmp_path / "agent.db"
    repo = AgentRepository(db_path)
    repo.upsert_conversation({"conversation_id": "conv_u1", "user_id": "u1", "title": "u1"})
    repo.upsert_conversation({"conversation_id": "conv_u2", "user_id": "u2", "title": "u2"})
    repo.upsert_message(
        {
            "message_id": "msg_u1",
            "conversation_id": "conv_u1",
            "user_id": "u1",
            "role": "user",
            "content": "u1 working memory 600519",
        }
    )
    repo.upsert_message(
        {
            "message_id": "msg_u2",
            "conversation_id": "conv_u2",
            "user_id": "u2",
            "role": "user",
            "content": "u2 working memory 000002",
        }
    )
    repo.upsert_conversation_summary(
        {
            "summary_id": "summary_u1",
            "conversation_id": "conv_u1",
            "user_id": "u1",
            "summary_text": "u1 episodic summary 600519",
            "metadata": {"stock_codes": ["600519"], "importance": 0.7},
        }
    )
    repo.upsert_agent_run(
        {
            "run_id": "run_u1",
            "conversation_id": "conv_u1",
            "user_id": "u1",
            "goal": "复盘 600519",
            "status": "completed",
            "metadata": {},
        }
    )

    layered = LayeredMemoryService(db_path).retrieve_layered_memory(
        user_id="u1",
        query="复盘 600519",
        session_id="conv_u1",
        run_id="run_u1",
        limit=5,
    )

    assert "u1 working memory 600519" in str(layered["working"])
    assert "u2 working memory 000002" not in str(layered)
    assert any("u1 episodic summary" in item["record"]["content"] for item in layered["episodic"])
    assert layered["policy"]["user_isolated"] is True

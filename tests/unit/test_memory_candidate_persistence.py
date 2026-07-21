from agent.memory.memory_manager import MemoryManager
from agent.memory.memory_types import MemoryStatus, MemoryType


def test_candidate_persists_in_sqlite_and_is_not_retrieved(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    manager = MemoryManager(db_path=db_path)
    candidates = manager.remember_candidate(
        "以后请记住我偏好稳健投资",
        user_id="u1",
        ttl_seconds=3600,
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.status == MemoryStatus.CANDIDATE
    assert candidate.memory_type == MemoryType.SEMANTIC

    reloaded = MemoryManager(db_path=db_path)
    pending = reloaded.list_candidates(user_id="u1")
    assert [item.memory_id for item in pending] == [candidate.memory_id]
    assert reloaded.retrieve_for_context(
        user_id="u1",
        query="稳健投资",
        relevance_threshold=0.0,
    )["items"] == []

    active = reloaded.confirm_candidate(candidate.memory_id, user_id="u1")
    assert active.status == MemoryStatus.ACTIVE
    assert active.metadata["user_confirmed"] is True
    assert reloaded.retrieve_for_context(
        user_id="u1",
        query="稳健投资",
        relevance_threshold=0.0,
    )["items"]

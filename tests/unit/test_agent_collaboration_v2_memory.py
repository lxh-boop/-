from agent.collaboration_v2.session_memory import SessionMemoryStore


def test_session_memory_is_sqlite_persistent_versioned_and_clearable(tmp_path):
    output_dir = tmp_path / "outputs"
    store = SessionMemoryStore(output_dir=output_dir)
    first = store.put(
        session_id="s1",
        key="comparison_targets",
        value=["600519", "000858"],
        source_type="user_message",
        confirmed=True,
        confidence=1.0,
    )
    assert first.changed is True
    assert first.item.version == 1

    # A new store instance must see the same conversation memory.
    reopened = SessionMemoryStore(output_dir=output_dir)
    loaded = reopened.get("s1", "comparison_targets")
    assert loaded is not None
    assert loaded.value == ["600519", "000858"]

    ignored = reopened.put(
        session_id="s1",
        key="comparison_targets",
        value=["000001", "000002"],
        source_type="agent_inference",
        confirmed=False,
        confidence=0.5,
    )
    assert ignored.changed is False
    assert ignored.conflict is True
    assert reopened.get("s1", "comparison_targets").value == ["600519", "000858"]

    matches = reopened.search("s1", "股票比较对象", task_id="t1", agent_id="EVIDENCE_RETRIEVER")
    assert matches
    assert matches[0].key == "comparison_targets"
    assert reopened.access_count("s1", "t1") == 1

    cleared = reopened.clear_session("s1")
    assert cleared["memory_items"] >= 1
    assert reopened.get("s1", "comparison_targets") is None

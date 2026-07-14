from __future__ import annotations

import json

from agent.artifacts import save_tool_result_artifact
from agent.context import ContextBundle, ContextResolver, ContextStore
from database.repositories import AgentRepository


def _db_path(tmp_path):
    return tmp_path / "agent_quant.db"


def test_context_store_save_load_append_and_expire(tmp_path):
    store = ContextStore(output_dir=tmp_path)
    bundle = ContextBundle(user_id="u1", conversation_id="conv1", run_id="run1", task_id="task1")

    ref = store.save_context_snapshot(bundle)
    loaded = store.load_context_snapshot(user_id="u1", context_id=bundle.context_id)

    assert ref["context_id"] == bundle.context_id
    assert loaded["context_id"] == bundle.context_id

    updated = store.append_tool_result(
        user_id="u1",
        context_id=bundle.context_id,
        tool_result={"success": True, "tool_name": "ranking", "message": "ok", "confirmation_token": "secret"},
    )
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True)

    assert updated["tool_context"]["result_summary"]["tool_name"] == "ranking"
    assert "secret" not in encoded

    updated = store.append_artifact_ref(
        user_id="u1",
        context_id=bundle.context_id,
        artifact_ref={"artifact_id": "artifact_1", "path": "D:/secret/path.json", "produced_outputs": ["ranking"]},
    )
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True)

    assert updated["artifact_context"]["artifact_refs"][0]["artifact_id"] == "artifact_1"
    assert "secret/path" not in encoded

    updated = store.append_runtime_event(
        user_id="u1",
        context_id=bundle.context_id,
        event={"event": "observed", "api_key": "sk-secret"},
    )
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True)

    assert updated["runtime_context"]["events"][0]["event"] == "observed"
    assert "sk-secret" not in encoded

    expired = store.expire_context(user_id="u1", context_id=bundle.context_id, reason="test")
    assert expired["metadata"]["status"] == "expired"


def test_context_resolver_artifact_ref_and_previous_tool_result(tmp_path):
    db_path = _db_path(tmp_path)
    AgentRepository(db_path)
    artifact_ref = save_tool_result_artifact(
        db_path=db_path,
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        tool_name="ranking",
        result={
            "success": True,
            "message": "ok",
            "data": {"records": [{"stock_code": "600519", "note": "large payload" * 200}]},
            "api_key": "sk-secret",
        },
    )
    resolver = ContextResolver(db_path=db_path, output_dir=tmp_path)

    resolved = resolver.resolve_artifact_ref(
        artifact_ref,
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
    )
    encoded = json.dumps(resolved, ensure_ascii=False, sort_keys=True)

    assert resolved["resolved"] is True
    assert resolved["artifact_id"] == artifact_ref["artifact_id"]
    assert "content_summary" in resolved
    assert "large payload" not in encoded
    assert "sk-secret" not in encoded
    assert "path" not in resolved

    previous = resolver.resolve_previous_tool_result(
        user_id="u1",
        artifact_id=artifact_ref["artifact_id"],
        conversation_id="conv1",
        run_id="run1",
    )
    assert previous["resolved"] is True
    assert previous["source"] == "artifact"

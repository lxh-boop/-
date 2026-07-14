from __future__ import annotations

import json

from agent.context import ContextManager, ContextResolver, ContextSanitizer
from agent.session.confirmation_manager import create_confirmation_plan
from agent.session.pending_action_store import get_pending_plan


def test_resolve_pending_plan_never_leaks_confirmation_token(tmp_path):
    plan = create_confirmation_plan(
        "u1",
        "execute_adjust_position",
        {
            "operation_type": "execute_adjust_position",
            "before_state_summary": {"cash": 1000},
            "proposed_changes": [{"stock_code": "600519", "action": "reduce"}],
            "after_state_preview": {"cash": 2000},
        },
        output_dir=tmp_path,
    )
    raw_plan = get_pending_plan("u1", plan["plan_id"], tmp_path)
    resolver = ContextResolver(output_dir=tmp_path)

    resolved = resolver.resolve_pending_plan(user_id="u1", plan_id=plan["plan_id"])
    approval_context = resolver.approval_context_from_plan(user_id="u1", plan_id=plan["plan_id"])
    encoded = json.dumps({"resolved": resolved, "approval": approval_context.to_dict()}, ensure_ascii=False, sort_keys=True)

    assert raw_plan["confirmation_token"]
    assert raw_plan["confirmation_token"] not in encoded
    assert raw_plan["confirmation_token_hash"] not in encoded
    assert resolved["confirmation_token_status"] == "present"
    assert approval_context.token_present is True
    assert approval_context.pending_plan_id == plan["plan_id"]
    assert approval_context.plan_hash == plan["plan_hash"]
    assert get_pending_plan("u1", plan["plan_id"], tmp_path)["execution_status"] == "pending"


def test_context_manager_builds_safe_approval_and_llm_context(tmp_path):
    plan = create_confirmation_plan(
        "u1",
        "capital_change",
        {
            "operation_type": "capital_change",
            "amount": 1000,
            "direction": "deposit",
            "warnings": ["will affect later replay"],
        },
        output_dir=tmp_path,
    )
    manager = ContextManager(output_dir=tmp_path)
    bundle = manager.create_initial_context(
        user_id="u1",
        query="confirm this plan",
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        page_state={"api_key": "sk-secret", "current_page": "AI Agent"},
    )
    bundle.approval_context = manager.build_approval_context(user_id="u1", plan_id=plan["plan_id"])
    snapshot_ref = manager.save_snapshot(bundle)
    llm_context = manager.build_llm_context(bundle, max_tokens=800)
    encoded = json.dumps(llm_context, ensure_ascii=False, sort_keys=True)

    assert snapshot_ref["context_id"] == bundle.context_id
    assert plan["confirmation_token"] not in encoded
    assert "sk-secret" not in encoded
    assert llm_context["approval_context"]["token_present"] is True
    assert llm_context["approval_context"]["pending_plan_id"] == plan["plan_id"]


def test_artifact_context_stores_refs_not_large_content():
    manager = ContextManager()
    bundle = manager.create_initial_context(user_id="u1", query="use artifact")
    manager.update_from_tool_result(
        bundle,
        {
            "success": True,
            "tool_name": "stock_news",
            "message": "ok",
            "data": {"chunks": [{"body": "large evidence body" * 500}]},
            "artifact_id": "artifact_abc",
            "metadata": {
                "artifact_ref": {
                    "artifact_id": "artifact_abc",
                    "artifact_type": "tool_result",
                    "path": "D:/secret/path.json",
                    "produced_outputs": ["evidence"],
                }
            },
        },
    )
    llm_context = ContextSanitizer().sanitize_for_llm(bundle)
    encoded = json.dumps(llm_context, ensure_ascii=False, sort_keys=True)

    assert "artifact_abc" in encoded
    assert "large evidence body" not in encoded
    assert "secret/path" not in encoded

from __future__ import annotations

import json

from agent.context import (
    ApprovalContext,
    ArtifactContext,
    ContextBundle,
    ContextWindow,
    ConversationContext,
    EvidenceContext,
    MemoryContext,
    PortfolioContext,
    RuntimeContext,
    TaskContext,
    ToolContext,
    UserContext,
)


def test_context_bundle_and_all_context_types_are_serializable():
    bundle = ContextBundle(
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        user_context=UserContext(user_id="u1", profile_summary={"risk": "medium"}),
        conversation_context=ConversationContext(conversation_id="conv1", recent_messages=[{"role": "user", "content": "hello"}]),
        task_context=TaskContext(task_id="task1", user_goal={"action": "query"}, task_plan={"steps": ["ranking"]}),
        tool_context=ToolContext(allowed_tools=["ranking"], result_summary={"success": True}),
        portfolio_context=PortfolioContext(account_summary={"total_asset": 100000}, positions_summary=[{"stock_code": "600519"}]),
        evidence_context=EvidenceContext(evidence_summary=[{"title": "news"}], source_refs=["src_1"]),
        artifact_context=ArtifactContext(artifact_refs=[{"artifact_id": "artifact_1"}]),
        approval_context=ApprovalContext(pending_plan_id="plan_1", plan_hash="hash_1", token_present=True),
        runtime_context=RuntimeContext(run_id="run1", phase="planning"),
        memory_context=MemoryContext(memory_refs=["mem_1"]),
    )

    payload = bundle.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["user_context"]["profile_summary"]["risk"] == "medium"
    assert payload["task_context"]["task_plan"]["steps"] == ["ranking"]
    assert "artifact_1" in encoded
    assert bundle.to_minimal_context()["approval"]["token_present"] is True


def test_context_window_trims_large_objects_but_keeps_required_refs():
    raw_positions = [{"stock_code": f"600{i:03d}", "note": "raw-position-detail" * 30} for i in range(80)]
    raw_evidence = [{"chunk_id": f"chunk_{i}", "body": "raw-evidence-detail" * 40} for i in range(80)]
    bundle = ContextBundle(
        user_id="u1",
        conversation_id="conv1",
        run_id="run1",
        task_id="task1",
        conversation_context=ConversationContext(
            recent_messages=[{"role": "user", "content": "old" * 500} for _ in range(10)]
            + [{"role": "user", "content": "latest request 600519"}]
        ),
        task_context=TaskContext(user_goal={"query": "latest request 600519"}, task_plan={"steps": ["use_artifact"]}, required_refs=["artifact_keep"]),
        portfolio_context=PortfolioContext(
            account_summary={"total_asset": 100000},
            positions_summary=[{"stock_code": "600519", "weight": 0.2}],
            raw_positions=raw_positions,
            artifact_refs=["portfolio_artifact"],
        ),
        evidence_context=EvidenceContext(
            evidence_summary=[{"title": "important evidence", "source_id": "src_1"}],
            source_refs=["src_1"],
            raw_evidence=raw_evidence,
        ),
        artifact_context=ArtifactContext(artifact_refs=[{"artifact_id": "artifact_keep"}], readable_artifact_ids=["artifact_keep"]),
        approval_context=ApprovalContext(pending_plan_id="plan_keep", token_present=True),
    )

    trimmed = ContextWindow(default_budget=500).trim_to_budget(bundle, max_tokens=500)
    encoded = json.dumps(trimmed, ensure_ascii=False, sort_keys=True)

    assert "artifact_keep" in encoded
    assert "plan_keep" in encoded
    assert "latest request 600519" in encoded
    assert "raw-position-detail" not in encoded
    assert "raw-evidence-detail" not in encoded
    assert trimmed["portfolio_context"]["raw_positions_summary"]["count"] == 80
    assert trimmed["evidence_context"]["raw_evidence_summary"]["count"] == 80

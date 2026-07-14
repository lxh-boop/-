from __future__ import annotations

from pathlib import Path

from agent.agent_specs import MARKET_INTELLIGENCE, RISK_OPERATION, SUPERVISOR
from agent.artifacts import ArtifactStore, save_tool_result_artifact
from agent.capability_index import (
    CapabilityIndexRepository,
    build_trusted_capability_index,
)
from agent.orchestration.multi_task_executor import execute_multi_intent_plan
from agent.router import route_agent_query


def test_complete_plan_does_not_query_capability_index() -> None:
    routed = route_agent_query("查看当前持仓", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["capability_gap"]["has_gap"] is False
    assert trace["capability_runtime"]["index_lookup_triggered"] is False
    assert trace["capability_runtime"]["candidate_count"] == 0


def test_capability_gap_triggers_readonly_index_lookup_only_after_validation_gap() -> None:
    routed = route_agent_query("target portfolio allocation", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["semantic_goal"]["action"] == "generate_target_portfolio_allocation"
    assert trace["initial_plan_validation"]["valid"] is False
    assert trace["capability_gap"]["missing_outputs"] == ["target_portfolio_allocation"]
    assert trace["capability_runtime"]["index_lookup_triggered"] is True
    assert trace["capability_runtime"]["selected_capability_ids"] == [
        "workflow:readonly_target_portfolio_allocation"
    ]
    assert trace["plan_validation"]["valid"] is True


def test_capability_index_view_filters_by_agent_allowlist_and_hides_implementation_files() -> None:
    repo = CapabilityIndexRepository()

    market_candidates = repo.query(
        agent_identity=MARKET_INTELLIGENCE,
        goal_action="preview_write_operation",
        missing_outputs=["operation_preview"],
        permission_scope="read",
    )
    assert market_candidates == []

    risk_candidates = repo.query(
        agent_identity=RISK_OPERATION,
        goal_action="preview_write_operation",
        missing_outputs=["operation_preview"],
        permission_scope="preview",
    )
    assert risk_candidates
    assert all("implementation_files" not in item for item in risk_candidates)
    assert all(item["permission_scope"] == "preview" for item in risk_candidates)


def test_runtime_capability_repository_has_no_mutation_surface() -> None:
    repo = CapabilityIndexRepository()

    assert callable(repo.query)
    assert callable(repo.report_stale_index)
    for forbidden in [
        "insert",
        "update",
        "delete",
        "enable",
        "disable",
        "refresh_from_source",
        "register_tool",
    ]:
        assert not hasattr(repo, forbidden)


def test_trusted_index_builder_generates_versioned_authorized_records() -> None:
    index = build_trusted_capability_index()

    assert index.index_version.startswith("capidx-")
    assert index.content_hash
    assert index.builder_version.startswith("phase10.3")
    assert any(record.capability_id == "tool:portfolio_state" for record in index.records)
    assert all(record.enabled for record in index.records)
    assert all(record.allowed_agent_types for record in index.records)


def test_artifact_store_allows_same_scope_read_and_blocks_cross_user(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    ref = save_tool_result_artifact(
        db_path=db_path,
        output_dir=tmp_path,
        user_id="u1",
        run_id="run_1",
        conversation_id="conv_1",
        task_id="task_1",
        tool_name="portfolio_state",
        result={
            "success": True,
            "message": "ok",
            "data": {"positions": [{"stock_code": "000001"}], "token": "secret-token"},
            "errors": [],
            "warnings": [],
        },
    )
    store = ArtifactStore(db_path=db_path, output_dir=tmp_path)

    same_user = store.read(ref["artifact_id"], user_id="u1", conversation_id="conv_1")
    cross_user = store.read(ref["artifact_id"], user_id="u2", conversation_id="conv_1")

    assert same_user is not None
    assert same_user["content"]["result"]["data"]["token"] == "***"
    assert "portfolio_state" in same_user["content"]["produced_outputs"]
    assert cross_user is None


def test_artifact_store_finds_reusable_artifact_in_same_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    ref = save_tool_result_artifact(
        db_path=db_path,
        output_dir=tmp_path,
        user_id="u1",
        run_id="run_1",
        conversation_id="conv_1",
        task_id="task_1",
        tool_name="portfolio_risk",
        result={"success": True, "message": "ok", "data": {"risk_level": "high"}, "errors": [], "warnings": []},
    )
    store = ArtifactStore(db_path=db_path, output_dir=tmp_path)

    reusable = store.find_reusable(
        user_id="u1",
        conversation_id="conv_1",
        run_id="run_1",
        producer_id="portfolio_risk",
        produced_outputs=["current_risk"],
    )

    assert reusable is not None
    assert reusable["artifact_id"] == ref["artifact_id"]


def test_same_run_artifact_cache_reduces_duplicate_tool_calls(tmp_path: Path) -> None:
    decomposition = {
        "tasks": [
            {"task_id": "task_1", "intent": "scheduler_status", "parameters": {}, "depends_on": []},
            {"task_id": "task_2", "intent": "scheduler_status", "parameters": {}, "depends_on": ["task_1"]},
        ]
    }

    result = execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        session_id="conv_1",
        context={"user_id": "u1", "run_id": "run_1"},
    )

    assert result["success"] is True
    assert result["artifact_metrics"]["artifact_lookup_count"] == 2
    assert result["artifact_metrics"]["artifact_reuse_count"] == 1
    assert result["task_results"]["task_2"]["execution_mode"] == "artifact_reuse"
    assert len(result["tool_calls"]) == 1


def test_supervisor_read_view_returns_small_relevant_candidate_set() -> None:
    repo = CapabilityIndexRepository()

    candidates = repo.query(
        agent_identity=SUPERVISOR,
        goal_action="query_portfolio_state",
        missing_outputs=["portfolio_state"],
        permission_scope="read",
        limit=2,
    )

    assert 1 <= len(candidates) <= 2
    assert candidates[0]["capability_id"] == "tool:portfolio_state"

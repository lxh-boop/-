from __future__ import annotations

import csv

from agent.capability_index import CapabilityIndexRepository
from agent.mcp.config import build_mcp_context_from_local_config
from agent.mcp.discovery import reset_discovery_cache
from agent.mcp.registry_bridge import default_example_tool_name
from agent.orchestration.multi_task_executor import _execute_single, execute_multi_intent_plan
from agent.tool_engine import AGENT_MAIN, AGENT_READ, OP_READ, OP_SYSTEM, execute_tool, get_tool_registry_v2


def _mcp_context() -> dict:
    return {
        "mcp": build_mcp_context_from_local_config(
            {
                "mcp_example_enabled": True,
                "mcp_example_allowed_tools": ["market_risk_summary"],
                "mcp_example_timeout_seconds": 5,
            }
        )
    }


def _ranking_fixture(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "ranking_latest.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "stock_code", "stock_name", "score"])
        writer.writeheader()
        writer.writerow({"rank": 1, "stock_code": "600176", "stock_name": "China Jushi", "score": "0.91"})
    return path


def setup_function() -> None:
    reset_discovery_cache()


def test_p1b_system_aux_tools_are_registered_with_legacy_aliases() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "user.profile.get": (OP_READ, ["user_profile"]),
        "sandbox.python_analysis": (OP_SYSTEM, ["python_sandbox_analysis"]),
        "system.scheduler_status": (OP_SYSTEM, ["scheduler_status"]),
        "report.list_latest": (OP_READ, ["report", "report_latest"]),
        "mcp.readonly.invoke": (OP_READ, ["mcp_tool"]),
    }

    for name, (operation_type, aliases) in expected.items():
        definition = registry.get(name)
        assert definition is not None
        assert definition.operation_type == operation_type
        for alias in aliases:
            assert registry.get(alias).name == name


def test_user_profile_v2_is_readonly_and_saves_artifact(tmp_path) -> None:
    result = execute_tool(
        "user_profile",
        {"user_id": "u1"},
        context={"user_id": "u1", "output_dir": tmp_path / "outputs", "db_path": tmp_path / "agent.db"},
        agent_type=AGENT_READ,
    )

    assert result.success is True
    assert result.metadata["canonical_tool_name"] == "user.profile.get"
    assert result.data["mutation_performed"] is False
    assert result.data["constraints"]
    assert result.artifact_id


def test_python_sandbox_v2_blocks_business_state_writes(tmp_path) -> None:
    result = execute_tool(
        "python_sandbox_analysis",
        {
            "code": "RESULT = {'total': sum(SNAPSHOT['values'])}",
            "snapshot": {"values": [2, 3, 5]},
        },
        context={"user_id": "u1", "output_dir": tmp_path / "outputs", "db_path": tmp_path / "agent.db"},
        agent_type=AGENT_MAIN,
    )
    blocked = execute_tool(
        "sandbox.python_analysis",
        {"code": "open('paper_account.json', 'w').write('bad')"},
        context={"output_dir": tmp_path / "outputs"},
        agent_type=AGENT_MAIN,
    )

    assert result.success is True
    assert result.metadata["canonical_tool_name"] == "sandbox.python_analysis"
    assert result.data["result"] == {"total": 10}
    assert result.data["business_state_write_allowed"] is False
    assert result.artifact_id
    assert blocked.success is False
    assert "sandbox_security_rejected" in ",".join(blocked.errors)


def test_scheduler_and_report_aliases_execute_through_v2(tmp_path) -> None:
    scheduler = _execute_single(
        "scheduler_status",
        {},
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        default_top_k=10,
        execution_context={"user_id": "u1", "root": str(tmp_path)},
    )
    report = _execute_single(
        "report_latest",
        {},
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        default_top_k=10,
        execution_context={"user_id": "u1"},
    )

    assert scheduler["success"] is True
    assert scheduler["tool_engine"]["canonical_tool_name"] == "system.scheduler_status"
    assert scheduler["artifact_id"]
    assert report["success"] is True
    assert report["tool_engine"]["canonical_tool_name"] == "report.list_latest"


def test_multi_task_scheduler_uses_v2_system_tool(tmp_path) -> None:
    result = execute_multi_intent_plan(
        {"tasks": [{"task_id": "task_1", "intent": "scheduler_status", "parameters": {}, "depends_on": []}]},
        user_id="u1",
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        context={"user_id": "u1", "root": str(tmp_path)},
    )

    assert result["success"] is True
    assert result["tool_calls"][0]["tool_name"] == "scheduler_status"
    assert result["task_results"]["task_1"]["success"] is True


def test_mcp_readonly_bridge_executes_and_blocks_unsafe_write(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    _ranking_fixture(output_dir)
    context = {**_mcp_context(), "output_dir": output_dir, "user_id": "u1"}
    result = execute_tool(
        "mcp.readonly.invoke",
        {"mcp_tool_name": default_example_tool_name(), "arguments": {"query": "stable portfolio", "top_k": 1}},
        context=context,
        agent_type=AGENT_READ,
    )
    blocked = execute_tool(
        "mcp.readonly.invoke",
        {"mcp_tool_name": "mcp.local_financial_evidence.unsafe_write_trade", "arguments": {"stock_code": "600176"}},
        context=context,
        agent_type=AGENT_READ,
    )

    assert result.success is True
    assert result.metadata["canonical_tool_name"] == "mcp.readonly.invoke"
    assert result.data["mutation_performed"] is False
    assert result.data["mcp_canonical_tool"] == default_example_tool_name()
    assert blocked.success is False
    assert "mcp_readonly_tool_not_allowed" in blocked.errors


def test_dynamic_mcp_intent_goes_through_v2_bridge_in_multi_task(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    _ranking_fixture(output_dir)
    name = default_example_tool_name()
    result = execute_multi_intent_plan(
        {"tasks": [{"task_id": "task_mcp", "intent": name, "parameters": {"query": "stable portfolio", "top_k": 1}}]},
        user_id="u1",
        output_dir=output_dir,
        db_path=tmp_path / "agent.db",
        context=_mcp_context(),
    )

    assert result["success"] is True
    assert result["tool_calls"][0]["tool_name"] == name
    assert result["task_results"]["task_mcp"]["data"]["v2_bridge_tool_name"] == "mcp.readonly.invoke"


def test_capability_index_exposes_p1b_tools() -> None:
    repo = CapabilityIndexRepository()
    supervisor = repo.query(
        agent_identity="supervisor",
        goal_action="run_readonly_python_analysis",
        missing_outputs=["sandbox_result"],
        permission_scope="read",
    )
    portfolio = repo.query(
        agent_identity="portfolio_analysis",
        goal_action="query_user_profile",
        missing_outputs=["constraints"],
        permission_scope="read",
    )

    assert any("sandbox.python_analysis" in item["registered_tool_names"] for item in supervisor)
    assert any("user.profile.get" in item["registered_tool_names"] for item in portfolio)

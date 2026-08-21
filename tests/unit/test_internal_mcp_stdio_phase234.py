from __future__ import annotations

from pathlib import Path

import pytest

from agent.mcp.client_manager import call_mcp_tool
from agent.mcp.config import (
    DATA_SERVER_ID,
    DATA_TOOL_NAMES,
    MODEL_SERVER_ID,
    MODEL_TOOL_NAMES,
    RAG_SERVER_ID,
    RAG_TOOL_NAMES,
    data_server_config,
    external_server_configs,
    mcp_sdk_version,
    model_server_config,
    rag_server_config,
)
from agent.mcp.discovery import discover_mcp_tools, reset_discovery_cache
from agent.mcp.runtime_registry import build_mcp_runtime_registry
from agent.collaboration.worker_directory import PORTFOLIO_ANALYST
from agent.tools.tool_registry import get_tool_registry
from agent.tool_engine import get_tool_registry_v2
from database.repositories import PredictionRepository
from local_config import DEFAULT_LOCAL_CONFIG


def _prediction_db(path: Path) -> Path:
    PredictionRepository(path).replace_snapshot(
        [
            {
                "date": "2026-08-20",
                "prediction_date": "2026-08-21",
                "stock_code": "000001",
                "stock_name": "Ping An Bank",
                "rank": 1,
                "score": 0.88,
                "pred_return": 0.03,
                "risk_score": 0.2,
                "risk_level": "low",
                "model_name": "kronos_mini",
            }
        ]
    )
    return path


def _context(server, *, db_path: Path, output_dir: Path) -> dict:
    return {
        "mcp": {
            "servers": [server.to_dict()],
            "discovery_ttl_seconds": 30,
        },
        "db_path": db_path,
        "output_dir": output_dir,
    }


def test_internal_mcp_configs_use_official_stdio_and_no_old_fixture() -> None:
    assert mcp_sdk_version().split(".", 1)[0] == "2"
    configs = {
        DATA_SERVER_ID: (data_server_config(), DATA_TOOL_NAMES),
        RAG_SERVER_ID: (rag_server_config(), RAG_TOOL_NAMES),
        MODEL_SERVER_ID: (model_server_config(), MODEL_TOOL_NAMES),
    }
    for server_id, (server, tool_names) in configs.items():
        assert server.server_id == server_id
        assert server.transport == "stdio"
        assert server.command.endswith("python.exe")
        assert server.args[:2] == ("-m", f"agent.mcp.servers.{server_id}_server")
        assert server.allowed_tools == tool_names
        assert Path(server.cwd).resolve() == Path(__file__).resolve().parents[2]

    assert "mcp_example_enabled" not in DEFAULT_LOCAL_CONFIG
    assert "mcp_data_enabled" in DEFAULT_LOCAL_CONFIG
    project_root = Path(__file__).resolve().parents[2]
    assert not (project_root / "agent" / "mcp" / "example_server.py").exists()
    assert not (project_root / "rag_retriever.py").exists()
    assert external_server_configs({"mcp_external_servers": []}) == []
    with pytest.raises(ValueError, match="external_mcp_tool_allowlist_required"):
        external_server_configs(
            {
                "mcp_external_servers": [
                    {
                        "server_id": "future_service",
                        "enabled": True,
                        "transport": "streamable_http",
                        "endpoint": "https://example.invalid/mcp",
                    }
                ]
            }
        )


def test_discovery_does_not_admit_or_project_tools(tmp_path: Path) -> None:
    db_path = _prediction_db(tmp_path / "agent_quant.db")
    server = data_server_config(timeout_seconds=20)
    context = _context(server, db_path=db_path, output_dir=tmp_path)
    reset_discovery_cache()

    result = discover_mcp_tools(
        context,
        force=True,
        server_id=DATA_SERVER_ID,
    )[0]
    assert result.success is True
    assert {tool.tool_name for tool in result.tools} == set(DATA_TOOL_NAMES)
    assert all(not tool.mapped and tool.transport == "stdio" for tool in result.tools)
    assert all(tool.discovery_status == "discovered" for tool in result.tools)
    assert all(tool.output_schema.get("type") == "object" for tool in result.tools)

    blocked = call_mcp_tool(
        "mcp.data.get_latest_ranking",
        {"top_k": 1},
        context=context,
    )
    assert blocked.success is False
    assert "runtime_admission_policy_missing" in blocked.errors

    registry = build_mcp_runtime_registry(context)
    record = registry.get("mcp.data.get_latest_ranking")
    assert record is not None
    assert record.discovered is True
    assert record.admitted is False
    assert record.registered is False
    assert record.projected is False


def test_model_mcp_reads_completed_real_inference_snapshot(tmp_path: Path) -> None:
    db_path = _prediction_db(tmp_path / "agent_quant.db")
    server = model_server_config(timeout_seconds=20)
    context = _context(server, db_path=db_path, output_dir=tmp_path)
    reset_discovery_cache()

    result = call_mcp_tool(
        "mcp.model.predict_stock_score",
        {"stock_code": "000001"},
        context=context,
        caller_tool_id="internal.prediction.get_stock",
        agent_type=PORTFOLIO_ANALYST,
    )
    assert result.success is True
    assert result.data["records"][0]["pred_return"] == 0.03
    assert result.data["inference_mode"] == "completed_task_snapshot"
    assert result.data["long_running_execution"] == "task_runtime"
    assert result.data["runtime_authority"] == "runtime_registry"

    wrong_caller = call_mcp_tool(
        "mcp.model.predict_stock_score",
        {"stock_code": "000001"},
        context=context,
        caller_tool_id="evidence.search_rag",
        agent_type=PORTFOLIO_ANALYST,
    )
    assert wrong_caller.success is False
    assert wrong_caller.errors == ["mcp_caller_tool_not_allowed"]


def test_runtime_registry_projects_worker_ids_not_raw_mcp_ids(tmp_path: Path) -> None:
    context = {
        "mcp": {
            "servers": [
                data_server_config(timeout_seconds=20).to_dict(),
                rag_server_config(timeout_seconds=20).to_dict(),
                model_server_config(timeout_seconds=20).to_dict(),
            ],
            "discovery_ttl_seconds": 30,
        },
        "db_path": tmp_path / "agent_quant.db",
        "output_dir": tmp_path,
    }
    registry = build_mcp_runtime_registry(context, force_discovery=True)
    report = registry.report()
    assert report["discovered_count"] == 13
    assert report["admitted_count"] == 6
    assert report["registered_count"] == 6
    assert report["projected_count"] == 6
    projected = registry.projected_worker_tool_ids()
    assert "internal.ranking.get_latest" in projected
    assert "evidence.search_rag" in projected
    assert all(not item.startswith("mcp.") for item in projected)
    raw_ids = {record.tool_id for record in registry.list_records()}
    assert raw_ids.isdisjoint(get_tool_registry(include_mcp=True))
    assert raw_ids.isdisjoint(
        definition.name for definition in get_tool_registry_v2().list()
    )


def test_mcp_output_schema_validation_fails_closed(monkeypatch, tmp_path: Path) -> None:
    context = _context(
        model_server_config(timeout_seconds=20),
        db_path=_prediction_db(tmp_path / "agent_quant.db"),
        output_dir=tmp_path,
    )
    reset_discovery_cache()
    monkeypatch.setattr(
        "agent.mcp.client_manager.call_stdio_tool",
        lambda *args, **kwargs: {"message": "missing required success"},
    )
    result = call_mcp_tool(
        "mcp.model.predict_rank",
        {"top_k": 1},
        context=context,
        caller_tool_id="internal.ranking.get_latest",
        agent_type=PORTFOLIO_ANALYST,
    )
    assert result.success is False
    assert result.data["status"] == "output_validation_failed"
    assert result.errors[0].startswith("mcp_output_schema_invalid:")


def test_worker_tool_ids_delegate_to_mcp_adapters() -> None:
    project_root = Path(__file__).resolve().parents[2]
    evidence_source = (project_root / "agent" / "worker_tools" / "evidence.py").read_text(
        encoding="utf-8"
    )
    internal_source = (
        project_root / "agent" / "worker_tools" / "internal_system.py"
    ).read_text(encoding="utf-8")

    assert 'EVIDENCE_SEARCH_RAG_TOOL = "evidence.search_rag"' in evidence_source
    assert 'INTERNAL_RANKING_GET_LATEST = "internal.ranking.get_latest"' in internal_source
    assert "invoke_worker_mcp" in evidence_source
    assert "invoke_worker_mcp" in internal_source
    assert "EvidenceService()" not in evidence_source
    assert "market_analysis_service.get_ranking" not in internal_source
    assert "portfolio_service.get_portfolio_state" not in internal_source

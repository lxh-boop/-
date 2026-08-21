from __future__ import annotations

import inspect
from pathlib import Path

from agent.mcp.config import data_server_config
from agent.mcp.models import MCPServerConfig, MCPToolInfo
from agent.runtime_reliability import RuntimePolicy
from agent.sandbox import run_python_analysis
from agent.services.python_sandbox_service import PythonSandboxService
from agent.tools.python_sandbox_tool import run_python_sandbox_analysis
from agent.tools.tool_registry import ToolSpec, get_tool_registry
from core.llm.ollama_manager import (
    _request_json,
    _run_ollama,
    create_project_model,
    get_ollama_version,
    is_ollama_running,
    list_local_models,
    pull_model,
    validate_local_model,
)
from local_config import DEFAULT_LOCAL_CONFIG
from server.api.tasks import TaskSubmitRequest
from server.task_runtime.manager import TaskManager
from server.task_runtime.store import TaskStore


def _default(function: object, parameter: str) -> object:
    return inspect.signature(function).parameters[parameter].default


def test_agent_task_llm_and_tool_defaults_use_prefix_99_policy() -> None:
    policy = RuntimePolicy.default()
    assert policy.agent_timeout_seconds == 9960.0
    assert policy.tool_timeout_seconds == 9930.0
    assert policy.resolve_for_tool("stock_rag").tool_timeout_seconds == 9990.0
    assert policy.resolve_for_tool("evidence.search_rag").tool_timeout_seconds == 9990.0

    assert ToolSpec.__dataclass_fields__["timeout_seconds"].default == 9930
    assert get_tool_registry()["python_sandbox_analysis"].timeout_seconds == 9910
    assert _default(run_python_analysis, "timeout_seconds") == 995.0
    assert _default(run_python_sandbox_analysis, "timeout_seconds") == 995.0
    assert _default(PythonSandboxService.run_analysis, "timeout_seconds") == 995.0

    assert MCPServerConfig.__dataclass_fields__["timeout_seconds"].default == 30.0
    assert MCPToolInfo.__dataclass_fields__["timeout_seconds"].default == 30.0
    assert data_server_config().timeout_seconds == 30.0

    assert DEFAULT_LOCAL_CONFIG["llm_request_timeout_seconds"] == 99120
    assert DEFAULT_LOCAL_CONFIG["mcp_data_timeout_seconds"] == 30.0


def test_task_runtime_defaults_use_prefix_99_policy() -> None:
    assert TaskSubmitRequest(task_type="diagnostic.sleep").timeout_seconds == 99600
    assert _default(TaskManager.submit, "timeout_seconds") == 99600
    assert _default(TaskStore.create, "timeout_seconds") == 99600


def test_ollama_operation_defaults_use_prefix_99_policy() -> None:
    assert _default(get_ollama_version, "timeout_seconds") == 9910
    assert _default(_request_json, "timeout_seconds") == 9910
    assert _default(is_ollama_running, "timeout_seconds") == 995
    assert _default(list_local_models, "timeout_seconds") == 9910
    assert _default(_run_ollama, "timeout_seconds") == 991800
    assert _default(pull_model, "timeout_seconds") == 991800
    assert _default(create_project_model, "timeout_seconds") == 99300
    assert _default(validate_local_model, "timeout_seconds") == 99120


def test_frontend_and_acceptance_long_timeouts_use_prefix_99_policy() -> None:
    project_root = Path(__file__).resolve().parents[2]

    expected_fragments = {
        "frontend/src/pages/agent/AgentPage.tsx": "timeout_seconds: 99900",
        "frontend/src/components/paper/PaperTaskActions.tsx": "timeout:991800",
        "frontend/src/components/paper/ProposalPanel.tsx": "timeout_seconds:997200",
        "frontend/src/hooks/useTask.ts": "timeout_seconds: 9930",
        "scripts/refactor/stage6_5_browser_acceptance.py": "timeout: int = 99420",
    }
    for relative, fragment in expected_fragments.items():
        content = (project_root / relative).read_text(encoding="utf-8-sig")
        assert fragment in content, relative

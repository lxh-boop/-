from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_executor_has_one_coordinator_call_and_no_legacy_router_call():
    text = _text("agent/executor.py")
    tree = ast.parse(text)
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "execute_unified_agent_request"
    ]
    assert len(calls) == 1
    assert "from agent.router import route_agent_query" not in text
    assert "routed = route_agent_query(" not in text
    assert "if is_language_setting_only(raw_query):" not in text


def test_collaboration_never_constructs_an_independent_model_client():
    directory = ROOT / "agent/collaboration"
    for path in directory.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from llm_client import LLMClient" not in text, path.name
        assert "LLMClient(" not in text, path.name
        # The annotation/import is allowed; construction is not.
        assert "LLMService(" not in text, path.name


def test_strategy_proposal_uses_private_tool_boundary():
    worker = _text("agent/collaboration/workers/strategy_proposal.py")
    definitions = _text("agent/worker_tools/proposal.py")

    assert "route_agent_query(" not in worker
    assert "execute_tool_legacy_dict" not in worker
    assert "AGENT_MAIN" not in worker
    assert "OP_PROPOSAL" in definitions
    assert "AGENT_WORKER" in definitions
    assert '"strategy.proposal"' in definitions


def test_public_legacy_entry_files_are_only_facades():
    router = _text("agent/router.py")
    registry = _text("agent/agent_registry.py")
    intent_router = _text("agent/intent_router.py")
    core = _text("agent/agent_core.py")
    assert "decompose_intent" not in router
    assert "extract_parameters" not in router
    assert "route_unified_agent_request" in router
    assert "event_keywords" not in registry
    assert "answer_with_registry" in registry and "run_agent_request" in registry
    assert "_contains_any" not in intent_router
    assert "route_unified_agent_request" in intent_router
    assert "route_intent(query)" not in core
    assert "run_agent_request" in core


def test_deprecated_action_fields_are_not_reintroduced():
    targets = list((ROOT / "agent/collaboration").rglob("*.py")) + [
        ROOT / "agent/router.py",
        ROOT / "agent/agent_core.py",
        ROOT / "agent/agent_registry.py",
        ROOT / "agent/intent_router.py",
    ]
    forbidden = ["final_action", "watchlist", "down_weight"]
    for path in targets:
        text = path.read_text(encoding="utf-8").lower()
        for marker in forbidden:
            assert marker not in text, f"{marker} in {path.name}"


def test_agent_dags_reuse_the_shared_validator():
    capability_validator = _text("agent/collaboration/capability_plan_validator.py")
    worker_validator = _text("agent/worker_planning/validator.py")
    dag_runtime = _text("agent/collaboration/dag_runtime.py")

    assert "DagValidator" in capability_validator
    assert "DagValidator" in worker_validator
    assert "def _validate_dependencies" not in capability_validator
    assert "def _topological_order" not in dag_runtime

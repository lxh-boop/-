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
    directory = ROOT / "agent/collaboration_v2"
    for path in directory.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from llm_client import LLMClient" not in text, path.name
        assert "LLMClient(" not in text, path.name
        # The annotation/import is allowed; construction is not.
        assert "LLMService(" not in text, path.name


def test_strategy_guard_never_calls_old_router():
    text = _text("agent/collaboration_v2/specialist_runtime.py")
    assert "from agent.router import route_agent_query" not in text
    assert "route_agent_query(" not in text
    assert "OP_PROPOSAL" in text
    assert "approval_granted=False" in text


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
    assert 'return "agent_collaboration_v2"' in intent_router
    assert "route_intent(query)" not in core
    assert "run_agent_request" in core


def test_ai_agent_confirmation_card_uses_control_gateway_facade():
    text = _text("app/pages/ai_agent.py")
    assert "execute_control_action" in text
    assert "execute_confirmed_plan_v2" not in text
    assert "reject_confirmation_plan" not in text


def test_deprecated_action_fields_are_not_reintroduced():
    targets = list((ROOT / "agent/collaboration_v2").glob("*.py")) + [
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

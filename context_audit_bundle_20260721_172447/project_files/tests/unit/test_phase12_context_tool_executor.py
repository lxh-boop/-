from __future__ import annotations

from agent.context import ContextBundle, ContextManager
from agent.tool_engine import AGENT_READ, OP_READ, ToolDefinition, ToolExecutor, ToolRegistry


def _description() -> str:
    return (
        "Function: test tool\n"
        "Applies when: unit testing context execution.\n"
        "Not for: production trading.\n"
        "Preconditions: valid runtime context and required inputs.\n"
        "Main inputs: none.\n"
        "Main outputs: context echo.\n"
        "Side effects: None; read-only."
    )


def _registry(calls: list[dict]):
    def handler(arguments, context):
        calls.append({"arguments": dict(arguments or {}), "context": dict(context or {})})
        return {"success": True, "message": "ok", "data": {"context_mode": context.get("context_mode"), "bundle_id": context.get("context_bundle_id")}}

    return ToolRegistry(
        [
            ToolDefinition(
                name="test.context_echo",
                display_name="Context Echo",
                description=_description(),
                input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": True},
                output_schema={"type": "object", "required_data_keys": []},
                execution_handler=handler,
                operation_type=OP_READ,
                allowed_agent_types=[AGENT_READ],
                permission_scope=OP_READ,
            )
        ]
    )


def test_tool_executor_accepts_context_bundle_and_tool_context(tmp_path):
    calls: list[dict] = []
    bundle = ContextBundle(user_id="u1", conversation_id="conv1", run_id="run1")
    executor = ToolExecutor(registry=_registry(calls))

    result = executor.execute(
        "test.context_echo",
        {},
        context={"user_id": "u1", "output_dir": tmp_path},
        context_bundle=bundle,
        tool_context=ContextManager(output_dir=tmp_path).build_tool_context(bundle),
        agent_type=AGENT_READ,
    )

    assert result.success is True
    assert calls[0]["context"]["context_mode"] == "bundle"
    assert calls[0]["context"]["context_bundle_id"] == bundle.context_id
    assert calls[0]["context"]["tool_context"]["context_id"] == bundle.context_id
    assert bundle.tool_context.result_summary["tool_name"] == "test.context_echo"


def test_tool_executor_old_call_without_context_bundle_stays_minimal():
    calls: list[dict] = []
    executor = ToolExecutor(registry=_registry(calls))

    result = executor.execute("test.context_echo", {}, agent_type=AGENT_READ)

    assert result.success is True
    assert calls[0]["context"]["context_mode"] == "minimal"

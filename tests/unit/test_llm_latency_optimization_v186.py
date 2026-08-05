from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from agent.collaboration.entry_decision import MainEntryDecisionPlanner
from agent.collaboration.worker_contracts import (
    WorkerContractViolation,
    string_schema,
    validate_schema,
)
from agent.collaboration.workers import entity_analysis, report_writer, risk, strategy_guard
from agent.tool_dag import planner as tool_dag_planner
from core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from core.llm.profiles import ModelProfile


class _CaptureLLM:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "mode": "analysis",
            "reason": "分析请求",
            "reply_language": "zh",
            "confidence": 1.0,
            "context_binding": {
                "entity_scope": "explicit_entities",
                "inherit_previous_focus": False,
                "reason": "明确实体",
            },
        }
        self.kwargs: dict = {}

    def generate_json(self, **kwargs):
        self.kwargs = dict(kwargs)
        return dict(self.payload)


def _qwen_profile() -> ModelProfile:
    return ModelProfile(
        profile_id="api:qwen:test",
        provider_id="openai_compatible",
        deployment_mode="api",
        model_name="qwen3.7-plus",
        base_url="https://example.invalid/v1",
        credential_ref="runtime:test",
        disable_thinking=False,
        request_timeout_seconds=120,
        max_retries=0,
        context_window=128000,
        supports_json_schema=True,
        supports_tools=True,
    )


def test_per_call_thinking_override_does_not_mutate_profile() -> None:
    profile = _qwen_profile()
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "x"}]

    disabled = OpenAICompatibleAdapter._prepared_messages(
        profile, messages, disable_thinking=True
    )
    enabled = OpenAICompatibleAdapter._prepared_messages(
        profile, messages, disable_thinking=False
    )

    # Remote Qwen uses the provider-level enable_thinking parameter instead of
    # spending prompt tokens on /no_think.
    assert disabled == messages
    assert enabled == messages
    assert OpenAICompatibleAdapter._provider_parameters(
        profile, disable_thinking=True
    ) == {"extra_body": {"enable_thinking": False}}
    assert OpenAICompatibleAdapter._provider_parameters(
        profile, disable_thinking=False
    ) == {"extra_body": {"enable_thinking": True}}
    assert profile.disable_thinking is False
    assert messages[0]["content"] == "system"


def test_entry_decision_disables_thinking_and_tightens_output() -> None:
    llm = _CaptureLLM()
    planner = MainEntryDecisionPlanner(llm_service=llm)
    planner.decide(
        query="分析贵州茅台",
        memory_summary="",
        execution_context={},
        language="zh",
    )
    assert llm.kwargs["disable_thinking"] is True
    assert llm.kwargs["max_output_tokens"] == 360


def test_stage_policy_keeps_reasoning_only_for_decision_nodes() -> None:
    coordinator_source = inspect.getsource(
        __import__("agent.collaboration.coordinator", fromlist=["AgentCollaborationCoordinator"])
    )
    main_planner_source = inspect.getsource(
        __import__("agent.collaboration.planner", fromlist=["CoordinatorPlanner"])
    )
    tool_source = inspect.getsource(tool_dag_planner)
    entity_source = inspect.getsource(entity_analysis)
    report_source = inspect.getsource(report_writer)
    risk_source = inspect.getsource(risk)
    strategy_source = inspect.getsource(strategy_guard)

    assert 'operation="extract_graph_entity_candidates"' in coordinator_source
    assert "disable_thinking=True" in coordinator_source
    assert "disable_thinking=True" in tool_source
    assert "disable_thinking=True" in report_source

    assert "disable_thinking=False" in main_planner_source
    assert "disable_thinking=False" in entity_source
    assert "disable_thinking=False" in risk_source
    assert "disable_thinking=False" in strategy_source
    assert "reasoning_budget" not in main_planner_source
    assert "thinking_budget" not in main_planner_source
    assert "reasoning_budget" not in entity_source
    assert "thinking_budget" not in entity_source


def test_string_max_length_contract_is_enforced() -> None:
    schema = string_schema(min_length=1, max_length=5)
    validate_schema("12345", schema)
    with pytest.raises(WorkerContractViolation) as exc:
        validate_schema("123456", schema)
    assert exc.value.code == "string_too_long"


def test_w09_output_is_structured_and_bounded() -> None:
    schema = entity_analysis._entity_analysis_llm_schema()
    props = schema["properties"]
    assert props["facts"]["maxItems"] == 8
    assert props["analysis"]["maxItems"] == 6
    assert props["model_signals"]["maxItems"] == 5
    assert props["uncertainties"]["maxItems"] == 6
    assert props["conclusion"]["maxLength"] == 500
    statement = props["facts"]["items"]["properties"]["statement"]
    assert statement["maxLength"] == 320


def test_w06_is_render_only_with_bounded_output() -> None:
    schema = report_writer._report_llm_schema()
    props = schema["properties"]
    assert report_writer._REPORT_MAX_OUTPUT_TOKENS == 2200
    assert props["sections"]["maxItems"] == 6
    section_props = props["sections"]["items"]["properties"]
    assert section_props["markdown"]["maxLength"] == 1600
    assert props["limitations"]["maxItems"] == 8
    prompt = report_writer._system_prompt("zh", SimpleNamespace())
    assert "不承担任何专业分析" in prompt
    assert "不得重新判断、推导或改写专业结论" in prompt

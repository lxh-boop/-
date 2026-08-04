from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.console_trace import (
    finalize_flow_markdown,
    flow_event,
    get_flow_markdown_path,
    get_llm_execution_timing,
    reset_flow_context,
)
from agent.llm_audit import activate_llm_audit_context, load_llm_events, record_llm_call
from core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from core.llm.profiles import ModelProfile


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __iter__(self):
        return iter(self._chunks)


class _FakeCompletions:
    def __init__(self, stream):
        self.stream = stream
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = dict(kwargs)
        return self.stream


class _FakeClient:
    def __init__(self, stream):
        self.chat = SimpleNamespace(completions=_FakeCompletions(stream))


class _Adapter(OpenAICompatibleAdapter):
    def __init__(self, client):
        self.client = client

    def _build_client(self, profile, credential):
        del profile, credential
        return self.client


def _profile() -> ModelProfile:
    return ModelProfile(
        profile_id="api:qwen:test",
        provider_id="qwen",
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


def test_streaming_adapter_records_observed_timing_boundaries(monkeypatch) -> None:
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    chunks = [
        SimpleNamespace(
            id="req-1",
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content="思考"))],
        ),
        SimpleNamespace(
            id="req-1",
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(content="O"))],
        ),
        SimpleNamespace(id="req-1", usage=usage, choices=[]),
    ]
    client = _FakeClient(_FakeStream(chunks))
    adapter = _Adapter(client)
    ticks = iter([0.00, 0.01, 0.02, 0.05, 0.08, 0.10, 0.11, 0.20])
    monkeypatch.setattr(
        "core.llm.adapters.openai_compatible.time.perf_counter",
        lambda: next(ticks),
    )

    response = adapter.generate(
        profile=_profile(),
        credential="secret",
        messages=[{"role": "user", "content": "test"}],
        temperature=0.0,
        max_output_tokens=100,
    )

    assert response.content == "O"
    assert response.usage["prompt_tokens"] == 100
    assert response.usage["cached_prompt_tokens"] == 40
    assert response.usage["reasoning_tokens"] == 7
    assert response.timing["measurement_mode"] == "stream_observed"
    assert response.timing["client_setup_ms"] == 10.0
    assert response.timing["queue_network_ms"] == 30.0
    assert response.timing["input_prefill_ms"] == 30.0
    assert response.timing["thinking_output_ms"] == 120.0
    assert response.timing["provider_transport_total_ms"] == 180.0
    assert response.timing["first_delta_kind"] == "reasoning"
    assert client.chat.completions.kwargs["stream"] is True
    assert client.chat.completions.kwargs["stream_options"] == {"include_usage": True}


def test_llm_timing_is_saved_to_audit_and_final_markdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_id = "agent_run_timing_v185"
    monkeypatch.setenv("AGENT_FLOW_TRACE", "1")
    monkeypatch.setenv("AGENT_FLOW_MARKDOWN_DIR", str(tmp_path / "flow"))
    flow_event("GRAPH_REQUEST", {"raw_message": "测试耗时"}, run_id=run_id)
    activate_llm_audit_context(
        run_id=run_id,
        conversation_id="conv-timing",
        output_dir=tmp_path,
        formal_entry_used=True,
        formal_entry_name="test",
        task_id="T01",
        worker_id="W06",
        agent_id="REPORT_WRITER",
    )
    event_id = record_llm_call(
        stage="graph_report_writer",
        provider="qwen",
        model="qwen3.7-plus",
        temperature=0.0,
        request_at="2026-08-04T00:00:00.000+00:00",
        response_at="2026-08-04T00:00:01.000+00:00",
        duration_ms=1000,
        success=True,
        operation="write_report",
        prompt_tokens=100,
        completion_tokens=25,
        total_tokens=125,
        cached_prompt_tokens=20,
        reasoning_tokens=5,
        timing={
            "measurement_mode": "stream_observed",
            "queue_network_ms": 100.0,
            "input_prefill_ms": 200.0,
            "thinking_output_ms": 700.0,
            "provider_transport_total_ms": 1000.0,
        },
    )
    assert event_id
    event = load_llm_events(tmp_path, run_id)[0]
    assert event["task_id"] == "T01"
    assert event["stage"] == "graph_report_writer"
    assert event["timing"]["input_prefill_ms"] == 200.0
    assert event["cached_prompt_tokens"] == 20
    summary = get_llm_execution_timing(run_id, "T01")
    assert summary["call_count"] == 1
    assert summary["provider_transport_ms_sum"] == 1000.0

    finalize_flow_markdown(
        run_id=run_id,
        question="测试耗时",
        execution={
            "run_total_duration_ms": 1500.0,
            "execution_status": "completed",
            "agent_timeline": [
                {
                    "task_id": "T01",
                    "agent_id": "REPORT_WRITER",
                    "duration_ms": 1200.0,
                    "dependency_wait_ms": 250.0,
                }
            ],
            "graph_runtime": {"worker_dag": {"tasks": []}},
            "graph_worker_results": {
                "items": [],
                "completed_count": 0,
                "failed_count": 0,
                "waiting_context_count": 0,
            },
        },
        runtime_status="completed",
        success=True,
    )
    text = Path(get_flow_markdown_path(run_id)).read_text(encoding="utf-8")
    assert "## LLM 分阶段耗时" in text
    assert "graph_report_writer" in text
    assert "输入预填充(ms)" in text
    assert "## Worker 依赖等待与执行耗时" in text
    assert "250.0" in text
    reset_flow_context()

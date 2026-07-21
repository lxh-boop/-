from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from agent.llm_audit import activate_llm_audit_context, load_llm_events
from core.llm import ollama_manager
from core.llm.runtime_settings import migrate_legacy_llm_config, resolve_active_llm_settings
from llm_client import LLMClient


def _profiles() -> dict:
    return {
        "llm_mode": "api",
        "llm_api_key": "remote-secret",
        "llm_api_base_url": "https://api.example.test/v1",
        "llm_api_model": "deepseek-v4-flash",
        "llm_local_base_url": "http://127.0.0.1:11434/v1",
        "llm_local_model": "stock-agent-qwen3-4b",
        "llm_local_disable_thinking": True,
    }


def test_legacy_api_settings_migrate_without_token_loss():
    migrated = migrate_legacy_llm_config({"llm_api_key": "keep-me", "llm_base_url": "https://old.example/v1", "llm_model": "old-model"})
    assert migrated["llm_api_key"] == "keep-me"
    assert migrated["llm_api_base_url"] == "https://old.example/v1"
    assert migrated["llm_api_model"] == "old-model"
    assert migrated["llm_mode"] == "api"


def test_api_and_local_profiles_are_saved_separately_and_manual_switch_only_changes_active_mode():
    profiles = _profiles()
    api = resolve_active_llm_settings(local_config=profiles)
    local = resolve_active_llm_settings(local_config={**profiles, "llm_mode": "local"})
    assert api.mode == "api" and api.api_key == "remote-secret"
    assert local.mode == "local" and local.api_key == "ollama"
    assert local.base_url == "http://127.0.0.1:11434/v1"
    assert profiles["llm_api_key"] == "remote-secret"
    assert profiles["llm_api_model"] == "deepseek-v4-flash"


def test_local_profile_stays_loopback_only_even_if_saved_value_is_invalid():
    settings = resolve_active_llm_settings(
        local_config={
            "llm_mode": "local",
            "llm_local_base_url": "https://remote.example/v1",
            "llm_max_retries": 9,
        }
    )
    assert settings.base_url == "http://127.0.0.1:11434/v1"
    assert settings.endpoint_scope == "loopback"
    assert settings.max_retries == 0


def test_api_mode_requires_real_key_and_local_mode_uses_dummy_ollama_key():
    api = resolve_active_llm_settings(local_config={"llm_mode": "api", "llm_api_base_url": "https://api.example/v1", "llm_api_model": "model"})
    with pytest.raises(RuntimeError, match="未配置 API Key"):
        LLMClient(settings=api)._build_client()
    local = resolve_active_llm_settings(local_config={"llm_mode": "local"})
    assert LLMClient(settings=local).api_key == "ollama"
    assert LLMClient(settings=local).base_url.startswith("http://127.0.0.1:11434")


def test_qwen_local_messages_append_no_think_once_without_mutating_input():
    settings = resolve_active_llm_settings(local_config={"llm_mode": "local", "llm_local_model": "stock-agent-qwen3-4b"})
    client = LLMClient(settings=settings)
    source = [{"role": "system", "content": "return JSON"}, {"role": "user", "content": "hello"}]
    prepared = client._prepared_messages(source)
    assert prepared[0]["content"].count("/no_think") == 1
    assert "/no_think" not in source[0]["content"]
    assert client._prepared_messages(prepared)[0]["content"].count("/no_think") == 1


def test_deepseek_extra_body_not_sent_to_ollama(monkeypatch):
    captured: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content="OK", reasoning_content=None))],
            )

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    local = resolve_active_llm_settings(local_config={"llm_mode": "local", "llm_local_model": "qwen3:4b"})
    client = LLMClient(settings=local)
    monkeypatch.setattr(client, "_build_client", lambda: FakeClient())
    assert client.chat([{"role": "user", "content": "hi"}]) == "OK"
    assert "extra_body" not in captured[0]


def test_mode_failures_do_not_fallback_and_audit_records_actual_provider(tmp_path, monkeypatch):
    settings = resolve_active_llm_settings(local_config={"llm_mode": "local"})
    client = LLMClient(settings=settings)
    monkeypatch.setattr(client, "_build_client", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    activate_llm_audit_context(
        run_id="run-local", conversation_id="conversation", output_dir=tmp_path,
        formal_entry_used=True, formal_entry_name="agent.executor.run_agent_request",
    )
    with pytest.raises(RuntimeError, match="未执行任何自动回退"):
        client.chat_audited([{"role": "user", "content": "hi"}], audit_stage="planner")
    event = load_llm_events(tmp_path, "run-local")[0]
    assert event["deployment_mode"] == "local"
    assert event["provider"] == "ollama_local"
    assert "remote-secret" not in str(event)


def test_ollama_command_uses_argument_list_and_invalid_model_rejected(monkeypatch):
    calls: list[object] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(ollama_manager, "is_ollama_installed", lambda: True)
    monkeypatch.setattr(ollama_manager.subprocess, "run", fake_run)
    result = ollama_manager._run_ollama(["pull", "qwen3:4b"])
    assert result.success and Path(calls[0][0][0]).name.lower() == "ollama.exe"
    assert calls[0][0][1:] == ["pull", "qwen3:4b"]
    assert "shell" not in calls[0][1]
    assert not ollama_manager.pull_model("bad model; rm -rf /").success


def test_missing_ollama_returns_actionable_error(monkeypatch):
    monkeypatch.setattr(ollama_manager, "is_ollama_installed", lambda: False)
    result = ollama_manager.list_local_models()
    assert not result.success
    assert "ollama.com/download/windows" in result.message

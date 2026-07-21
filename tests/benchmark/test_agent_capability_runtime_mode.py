from __future__ import annotations

from benchmarks.agent_capability.config import BenchmarkRuntimeConfig
from core.llm.runtime_settings import resolve_active_llm_settings


def test_benchmark_hash_differs_between_api_and_local():
    api = resolve_active_llm_settings(local_config={"llm_mode": "api", "llm_api_key": "x", "llm_api_base_url": "https://api.example/v1", "llm_api_model": "remote"})
    local = resolve_active_llm_settings(local_config={"llm_mode": "local", "llm_local_model": "stock-agent-qwen3-4b"})
    api_config = BenchmarkRuntimeConfig(provider=api.provider, model=api.model, deployment_mode=api.mode, endpoint_scope=api.endpoint_scope)
    local_config = BenchmarkRuntimeConfig(provider=local.provider, model=local.model, deployment_mode=local.mode, endpoint_scope=local.endpoint_scope, concurrency=1, case_timeout_seconds=600, request_retries=0)
    assert api_config.config_hash != local_config.config_hash
    assert local_config.concurrency == 1
    assert local_config.public_dict()["deployment_mode"] == "local"

"""Configuration and safe local-model resolution for the L1 benchmark."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.llm.runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = ROOT / "outputs" / "benchmarks" / "agent_capability"
CASES_ROOT = Path(__file__).resolve().parent / "cases"
FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class BenchmarkRuntimeConfig:
    """Public, reproducible runtime policy.  Credentials never enter this object."""

    provider: str
    model: str
    deployment_mode: str = "api"
    endpoint_scope: str = "remote"
    request_timeout_seconds: int = 120
    temperature: float = 0.0
    planner_max_output_tokens: int = 3000
    review_max_output_tokens: int = 2400
    completion_max_output_tokens: int = 1300
    report_max_output_tokens: int = 2000
    critic_max_output_tokens: int = 1800
    request_retries: int = 1
    case_timeout_seconds: int = 150
    max_replans: int = 2
    max_tool_calls: int = 24
    concurrency: int = 2
    trace_schema_version: str = "l1_llm_receipt_v2"
    scorer_version: str = "l1_validity_partition_v2"

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.public_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_llm_settings() -> tuple[dict[str, Any], BenchmarkRuntimeConfig]:
    """Read the user's local configuration without printing or persisting secrets."""
    from local_config import load_local_config

    local = dict(load_local_config() or {})
    active = resolve_active_llm_settings(local_config=local)
    settings = {
        "llm_api_key": active.api_key,
        "llm_base_url": active.base_url,
        "llm_model": active.model,
        "llm_settings": active,
    }
    config = BenchmarkRuntimeConfig(
        provider=active.provider,
        model=active.model or "unconfigured",
        deployment_mode=active.mode,
        endpoint_scope=active.endpoint_scope,
        request_timeout_seconds=active.request_timeout_seconds,
        concurrency=1 if active.mode == "local" else 2,
        case_timeout_seconds=600 if active.mode == "local" else 150,
        request_retries=0 if active.mode == "local" else 1,
    )
    return settings, config


def ensure_roots(root: Path = BENCHMARK_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "isolated_workspaces").mkdir(parents=True, exist_ok=True)
    FIXTURES_ROOT.mkdir(parents=True, exist_ok=True)

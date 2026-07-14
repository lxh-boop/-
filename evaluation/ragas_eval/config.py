from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_K_VALUES = [1, 3, 5, 10, 20, 50]


def _safe_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in [None, ""] else default
    except ValueError:
        return default


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(float(value)) if value not in [None, ""] else default
    except ValueError:
        return default


def _load_yaml(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("读取 YAML 配置需要 PyYAML，请先安装 pyyaml。") from exc
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _deep_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _base_url_domain(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    return parsed.netloc or parsed.path.split("/")[0]


def _load_project_llm_config() -> dict[str, Any]:
    try:
        from local_config import load_local_config

        config = load_local_config()
        return {
            "api_key": str(config.get("llm_api_key") or "").strip(),
            "base_url": str(config.get("llm_base_url") or "").strip(),
            "model": str(config.get("llm_model") or "").strip(),
        }
    except Exception:
        return {"api_key": "", "base_url": "", "model": ""}


@dataclass(slots=True)
class RagasEvalRuntimeConfig:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    embedding_model: str = ""
    temperature: float = 0.0
    timeout_seconds: int = 120
    max_workers: int = 2
    retry_count: int = 2
    judge_language: str = "chinese"
    adapt_prompts: bool = True
    adapt_prompt_instruction: bool = False
    response_relevancy_strictness: int = 1
    config_source: str = "env"
    no_llm: bool = False

    @classmethod
    def from_env(cls) -> "RagasEvalRuntimeConfig":
        project_llm = _load_project_llm_config()
        env_api_key = os.environ.get("RAGAS_EVAL_API_KEY", "").strip()
        env_base_url = os.environ.get("RAGAS_EVAL_BASE_URL", "").strip()
        env_model = os.environ.get("RAGAS_EVAL_MODEL", "").strip()
        config_source = "env" if (env_api_key or env_base_url or env_model) else "local_app_config"
        return cls(
            provider=os.environ.get("RAGAS_EVAL_PROVIDER", "").strip() or "openai_compatible",
            model=env_model or project_llm.get("model", ""),
            api_key=env_api_key or project_llm.get("api_key", ""),
            base_url=env_base_url or project_llm.get("base_url", ""),
            embedding_model=os.environ.get("RAGAS_EVAL_EMBEDDING_MODEL", "").strip(),
            temperature=_safe_float(os.environ.get("RAGAS_EVAL_TEMPERATURE"), 0.0),
            timeout_seconds=_safe_int(os.environ.get("RAGAS_EVAL_TIMEOUT_SECONDS"), 120),
            max_workers=_safe_int(os.environ.get("RAGAS_EVAL_MAX_WORKERS"), 2),
            retry_count=_safe_int(os.environ.get("RAGAS_EVAL_RETRY_COUNT"), 2),
            judge_language=os.environ.get("RAGAS_EVAL_JUDGE_LANGUAGE", "chinese").strip() or "chinese",
            adapt_prompts=_safe_bool(os.environ.get("RAGAS_EVAL_ADAPT_PROMPTS"), True),
            adapt_prompt_instruction=_safe_bool(os.environ.get("RAGAS_EVAL_ADAPT_PROMPT_INSTRUCTION"), False),
            response_relevancy_strictness=_safe_int(os.environ.get("RAGAS_EVAL_RESPONSE_RELEVANCY_STRICTNESS"), 1),
            config_source=config_source,
        )

    def sanitized(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "base_url_domain": _base_url_domain(self.base_url),
            "embedding_model": self.embedding_model or "",
            "embedding_configured": bool(self.embedding_model),
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
            "max_workers": self.max_workers,
            "retry_count": self.retry_count,
            "judge_language": self.judge_language,
            "adapt_prompts": self.adapt_prompts,
            "adapt_prompt_instruction": self.adapt_prompt_instruction,
            "response_relevancy_strictness": self.response_relevancy_strictness,
            "config_source": self.config_source,
            "no_llm": self.no_llm,
        }


@dataclass(slots=True)
class RagasEvalConfig:
    experiment_name: str = "ragas_eval"
    mode: str = "retrieval"
    top_k: int = 10
    decision_time_filter: bool = True
    deterministic_metrics: list[str] = field(default_factory=lambda: [
        "id_context_precision",
        "id_context_recall",
        "recall_at_k",
        "precision_at_k",
        "hit_rate_at_k",
        "mrr",
        "ndcg_at_k",
        "future_leak_rate",
        "wrong_stock_rate",
        "duplicate_event_rate",
        "direct_evidence_rate",
    ])
    llm_metrics: list[str] = field(default_factory=lambda: [
        "context_precision",
        "context_recall",
        "content_faithfulness",
        "response_relevancy",
    ])
    k_values: list[int] = field(default_factory=lambda: list(DEFAULT_K_VALUES))
    quality_gates: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "future_leak_rate": {"max": 0.0},
        "wrong_stock_rate": {"max": 0.02},
        "duplicate_event_rate": {"max": 0.10},
        "recall_at_10": {"min": 0.80},
        "context_precision": {"min": 0.70},
        "context_recall": {"min": 0.70},
        "content_faithfulness": {"min": 0.80},
        "response_relevancy": {"min": 0.70},
    })
    runtime: RagasEvalRuntimeConfig = field(default_factory=RagasEvalRuntimeConfig.from_env)
    raw_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RagasEvalConfig":
        raw = _load_yaml(path)
        runtime = RagasEvalRuntimeConfig.from_env()
        runtime.max_workers = int(_deep_get(raw, "runtime.max_workers", runtime.max_workers))
        runtime.timeout_seconds = int(_deep_get(raw, "runtime.timeout_seconds", runtime.timeout_seconds))
        runtime.retry_count = int(_deep_get(raw, "runtime.retry_count", runtime.retry_count))
        runtime.embedding_model = str(
            _deep_get(raw, "runtime.embedding_model", runtime.embedding_model)
        ).strip()
        runtime.judge_language = str(_deep_get(raw, "runtime.judge_language", runtime.judge_language))
        runtime.adapt_prompts = _safe_bool(_deep_get(raw, "runtime.adapt_prompts", runtime.adapt_prompts), runtime.adapt_prompts)
        runtime.adapt_prompt_instruction = _safe_bool(
            _deep_get(raw, "runtime.adapt_prompt_instruction", runtime.adapt_prompt_instruction),
            runtime.adapt_prompt_instruction,
        )
        runtime.response_relevancy_strictness = int(
            _deep_get(raw, "runtime.response_relevancy_strictness", runtime.response_relevancy_strictness)
        )
        config = cls(
            experiment_name=str(_deep_get(raw, "experiment.name", "ragas_eval")),
            mode=str(_deep_get(raw, "experiment.mode", "retrieval")),
            top_k=int(_deep_get(raw, "retrieval.top_k", 10)),
            decision_time_filter=bool(_deep_get(raw, "retrieval.decision_time_filter", True)),
            deterministic_metrics=list(_deep_get(raw, "metrics.deterministic", cls().deterministic_metrics)),
            llm_metrics=list(_deep_get(raw, "metrics.llm_based", cls().llm_metrics)),
            quality_gates=dict(_deep_get(raw, "quality_gates", cls().quality_gates) or {}),
            runtime=runtime,
            raw_config=raw,
        )
        return config

    def snapshot(self) -> dict[str, Any]:
        return {
            "experiment": {"name": self.experiment_name, "mode": self.mode},
            "retrieval": {
                "top_k": self.top_k,
                "decision_time_filter": self.decision_time_filter,
            },
            "metrics": {
                "deterministic": self.deterministic_metrics,
                "llm_based": self.llm_metrics,
                "k_values": self.k_values,
            },
            "quality_gates": self.quality_gates,
            "runtime": self.runtime.sanitized(),
        }

import json
from pathlib import Path
from typing import Any, Dict

from core.config.paths import get_local_config_path, is_frozen_app


LOCAL_CONFIG_PATH = (
    str(get_local_config_path()) if is_frozen_app() else "local_app_config.json"
)


DEFAULT_LOCAL_CONFIG = {
    "tushare_token": "[REDACTED]",
    "llm_api_key": "[REDACTED]",
    "llm_mode": "api",
    "llm_api_provider": "openai_compatible",
    "llm_api_base_url": "",
    "llm_api_model": "",
    "llm_api_disable_thinking": False,
    "llm_api_context_window": 128000,
    "llm_api_supports_json_schema": True,
    "llm_api_supports_tools": True,
    "llm_local_base_url": "http://127.0.0.1:11434/v1",
    "llm_local_model": "stock-agent-qwen3-4b",
    "llm_local_disable_thinking": True,
    "llm_local_context_window": 32768,
    "llm_local_supports_json_schema": False,
    "llm_local_supports_tools": False,
    "llm_request_timeout_seconds": 120,
    "llm_max_retries": 0,
    "current_user_id": "default",
    "model_backend": "zoo:chronos_bolt_small",
    "dft_unet_checkpoint_path": "",
    "auto_retrain_enabled": False,
    "auto_retrain_hour": 20,
    "auto_retrain_minute": 0,
    "model_version": "latest",
    "page_zoom_percent": 100,
    "mcp_example_enabled": False,
    "mcp_example_allowed_tools": ["market_risk_summary"],
    "mcp_example_timeout_seconds": 5.0,
    "mcp_discovery_ttl_seconds": 300,
}


def _legacy_compatible_view(config: Dict[str, Any]) -> Dict[str, Any]:
    """Expose read-only aliases for explicitly unmigrated legacy consumers."""

    view = dict(config)
    view["llm_base_url"] = str(view.get("llm_api_base_url") or "")
    view["llm_model"] = str(view.get("llm_api_model") or "")
    return view


def load_local_config() -> Dict[str, Any]:
    path = Path(LOCAL_CONFIG_PATH)
    if not path.exists():
        return _legacy_compatible_view(DEFAULT_LOCAL_CONFIG)

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        cfg = DEFAULT_LOCAL_CONFIG.copy()
        cfg.update(data)
        # Legacy aliases are read only at this migration boundary.
        if not str(cfg.get("llm_api_base_url") or "").strip() and str(cfg.get("llm_base_url") or "").strip():
            cfg["llm_api_base_url"] = str(cfg["llm_base_url"]).strip()
        if not str(cfg.get("llm_api_model") or "").strip() and str(cfg.get("llm_model") or "").strip():
            cfg["llm_api_model"] = str(cfg["llm_model"]).strip()
        if str(cfg.get("llm_mode") or "").strip().lower() not in {"api", "local"}:
            cfg["llm_mode"] = "api"
        return _legacy_compatible_view(cfg)

    except Exception:
        return _legacy_compatible_view(DEFAULT_LOCAL_CONFIG)


def save_local_config(config: Dict[str, Any]) -> None:
    cfg = DEFAULT_LOCAL_CONFIG.copy()
    cfg.update(config)
    if not str(cfg.get("llm_api_base_url") or "").strip() and str(cfg.get("llm_base_url") or "").strip():
        cfg["llm_api_base_url"] = str(cfg["llm_base_url"]).strip()
    if not str(cfg.get("llm_api_model") or "").strip() and str(cfg.get("llm_model") or "").strip():
        cfg["llm_api_model"] = str(cfg["llm_model"]).strip()
    # Do not perpetuate legacy aliases after migration.
    cfg.pop("llm_base_url", None)
    cfg.pop("llm_model", None)

    path = Path(LOCAL_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

import json
from pathlib import Path
from typing import Any, Dict

from core.config.paths import get_local_config_path, is_frozen_app


LOCAL_CONFIG_PATH = (
    str(get_local_config_path()) if is_frozen_app() else "local_app_config.json"
)


DEFAULT_LOCAL_CONFIG = {
    "tushare_token": "",
    "llm_api_key": "",
    "llm_base_url": "",
    "llm_model": "",
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


def load_local_config() -> Dict[str, Any]:
    path = Path(LOCAL_CONFIG_PATH)
    if not path.exists():
        return DEFAULT_LOCAL_CONFIG.copy()

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        cfg = DEFAULT_LOCAL_CONFIG.copy()
        cfg.update(data)
        return cfg

    except Exception:
        return DEFAULT_LOCAL_CONFIG.copy()


def save_local_config(config: Dict[str, Any]) -> None:
    cfg = DEFAULT_LOCAL_CONFIG.copy()
    cfg.update(config)

    path = Path(LOCAL_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

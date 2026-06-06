import json
import os
from typing import Any, Dict


LOCAL_CONFIG_PATH = "local_app_config.json"


DEFAULT_LOCAL_CONFIG = {
    "tushare_token": "",
    "llm_api_key": "",
    "llm_base_url": "",
    "llm_model": "",
    "model_backend": "torch_mlp_alpha158",
    "dft_unet_checkpoint_path": "",
    "auto_retrain_enabled": False,
    "auto_retrain_hour": 20,
    "auto_retrain_minute": 0,
    "model_version": "latest",
}


def load_local_config() -> Dict[str, Any]:
    if not os.path.exists(LOCAL_CONFIG_PATH):
        return DEFAULT_LOCAL_CONFIG.copy()

    try:
        with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        cfg = DEFAULT_LOCAL_CONFIG.copy()
        cfg.update(data)
        return cfg

    except Exception:
        return DEFAULT_LOCAL_CONFIG.copy()


def save_local_config(config: Dict[str, Any]) -> None:
    cfg = DEFAULT_LOCAL_CONFIG.copy()
    cfg.update(config)

    with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

from __future__ import annotations

from pathlib import Path

from .lightgbm_backend import LightGBMBackend


TORCH_MLP_BACKEND = "torch_mlp"
LIGHTGBM_BACKEND = "lightgbm"


def list_available_model_backends() -> list[str]:
    return [TORCH_MLP_BACKEND, LIGHTGBM_BACKEND]


def load_model_backend(model_backend: str, save_dir: str | None = None, **kwargs):
    backend = model_backend.strip().lower()

    if backend in {"torch_mlp", "torch_mlp_alpha158"}:
        return None

    if backend == LIGHTGBM_BACKEND:
        model = LightGBMBackend(**kwargs)
        if save_dir:
            return model.load(Path(save_dir))
        return model

    raise ValueError(f"未知模型后端：{model_backend}")

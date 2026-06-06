from __future__ import annotations

from model_zoo_backend import (
    is_zoo_backend,
    load_zoo_adapter,
    registered_zoo_backends,
    zoo_model_name_from_backend,
)

from .dft_unet_adapter import DFTUNetAdapter


TORCH_MLP_BACKEND = "torch_mlp_alpha158"
DFT_UNET_BACKEND = "dft_unet_external"


def list_available_model_backends():
    return [TORCH_MLP_BACKEND, DFT_UNET_BACKEND, *registered_zoo_backends().values()]


def load_model_backend(model_backend: str, **kwargs):
    if model_backend == TORCH_MLP_BACKEND:
        return None

    if model_backend == DFT_UNET_BACKEND:
        adapter = DFTUNetAdapter(
            checkpoint_path=kwargs.get("checkpoint_path"),
            device=kwargs.get("device", "cpu"),
        )
        return adapter.load()

    if is_zoo_backend(model_backend):
        return load_zoo_adapter(
            zoo_model_name_from_backend(model_backend),
            device=kwargs.get("device", "cpu"),
            context_length=kwargs.get("context_length", 64),
            batch_size=kwargs.get("batch_size", 64),
        )

    raise ValueError(f"unsupported model backend: {model_backend}")

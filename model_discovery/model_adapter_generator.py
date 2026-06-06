from __future__ import annotations

from .model_candidate_schema import ModelCandidate


def suggest_adapter_name(candidate: ModelCandidate) -> str:
    source = (candidate.source_type or "").lower()
    name = candidate.model_name.lower()
    if "huggingface" in source or candidate.hf_url:
        return "hf_timeseries_adapter"
    if "lightgbm" in name:
        return "lightgbm_adapter"
    if "dft" in name:
        return "dft_unet_adapter"
    if candidate.has_pretrained_weight:
        return "pytorch_checkpoint_adapter"
    return "github_model_adapter"


def adapter_plan(candidate: ModelCandidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "model_name": candidate.model_name,
        "adapter_name": suggest_adapter_name(candidate),
        "input_type": candidate.input_type,
        "output_type": candidate.output_type,
        "data_format_required": candidate.data_format_required,
        "notes": "Adapter skeleton planning only; implementation happens after repository/checkpoint inspection.",
    }

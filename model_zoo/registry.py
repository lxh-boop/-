from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


EXTERNAL_ZOO_DIR = Path("models") / "external_zoo"


@dataclass(frozen=True)
class ModelZooEntry:
    name: str
    family: str
    provider: str
    hf_repo: str
    local_subdir: str
    file_format: str
    task: str
    input_type: str
    license: str
    priority: str
    notes: str
    adapter: str
    status: str = "registered"

    @property
    def local_path(self) -> Path:
        return EXTERNAL_ZOO_DIR / self.family / self.local_subdir

    def to_metadata(self) -> dict:
        data = asdict(self)
        data["local_path"] = str(self.local_path)
        return data


MODEL_ZOO: dict[str, ModelZooEntry] = {
    "chronos_bolt_small": ModelZooEntry(
        name="chronos_bolt_small",
        family="chronos",
        provider="amazon",
        hf_repo="amazon/chronos-bolt-small",
        local_subdir="chronos_bolt_small",
        file_format="huggingface_safetensors",
        task="time_series_forecasting",
        input_type="univariate_return_sequence",
        license="apache-2.0",
        priority="high",
        notes="Chronos-Bolt small; first supported zero-shot K-line baseline.",
        adapter="chronos",
    ),
    "chronos_t5_small": ModelZooEntry(
        name="chronos_t5_small",
        family="chronos",
        provider="amazon",
        hf_repo="amazon/chronos-t5-small",
        local_subdir="chronos_t5_small",
        file_format="huggingface",
        task="time_series_forecasting",
        input_type="univariate_return_sequence",
        license="apache-2.0",
        priority="high",
        notes="Registered for later comparison; not downloaded by default.",
        adapter="chronos",
    ),
    "timesfm_2_0_500m": ModelZooEntry(
        name="timesfm_2_0_500m",
        family="timesfm",
        provider="google",
        hf_repo="google/timesfm-2.0-500m-pytorch",
        local_subdir="timesfm_2_0_500m",
        file_format="huggingface",
        task="time_series_forecasting",
        input_type="univariate_return_sequence",
        license="apache-2.0",
        priority="high",
        notes="Registered and downloadable; adapter is a guarded optional dependency.",
        adapter="timesfm",
    ),
    "moment_small": ModelZooEntry(
        name="moment_small",
        family="moment",
        provider="AutonLab",
        hf_repo="AutonLab/MOMENT-1-small",
        local_subdir="moment_small",
        file_format="huggingface",
        task="time_series_foundation_model",
        input_type="multivariate_ohlcv_sequence",
        license="mit",
        priority="high",
        notes="Registered and downloadable; adapter is a guarded optional dependency.",
        adapter="moment",
    ),
    "moment_base": ModelZooEntry(
        name="moment_base",
        family="moment",
        provider="AutonLab",
        hf_repo="AutonLab/MOMENT-1-base",
        local_subdir="moment_base",
        file_format="huggingface",
        task="time_series_foundation_model",
        input_type="multivariate_ohlcv_sequence",
        license="mit",
        priority="high",
        notes="Registered and downloadable; larger than moment_small.",
        adapter="moment",
    ),
    "moirai_small": ModelZooEntry(
        name="moirai_small",
        family="moirai",
        provider="Salesforce",
        hf_repo="Salesforce/moirai-1.0-R-small",
        local_subdir="moirai_small",
        file_format="huggingface",
        task="probabilistic_time_series_forecasting",
        input_type="univariate_or_multivariate_sequence",
        license="apache-2.0",
        priority="medium_high",
        notes="Registered and downloadable; adapter is a guarded optional dependency.",
        adapter="moirai",
    ),
}


ALIASES = {
    "chronos": "chronos_bolt_small",
    "timesfm": "timesfm_2_0_500m",
    "moment": "moment_small",
    "moirai": "moirai_small",
}


def normalize_model_name(name: str) -> str:
    key = str(name or "").strip().lower().replace("-", "_")
    return ALIASES.get(key, key)


def get_model_entry(name: str) -> ModelZooEntry:
    key = normalize_model_name(name)
    if key not in MODEL_ZOO:
        raise KeyError(f"unknown external zoo model: {name}")
    return MODEL_ZOO[key]


def list_model_entries() -> list[ModelZooEntry]:
    return list(MODEL_ZOO.values())


def list_model_names() -> list[str]:
    return list(MODEL_ZOO)

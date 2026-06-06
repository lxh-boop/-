from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .model_candidate_schema import ModelCandidate


HF_QUERIES = [
    "time series forecasting",
    "chronos time series",
    "timesfm",
    "moment time series",
    "moirai forecasting",
    "stock forecasting",
]


def search_huggingface(per_query: int = 5, timeout: int = 12) -> tuple[list[ModelCandidate], list[dict]]:
    candidates: list[ModelCandidate] = []
    errors: list[dict] = []

    for query in HF_QUERIES:
        params = urllib.parse.urlencode({"search": query, "limit": per_query})
        url = f"https://huggingface.co/api/models?{params}"
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "stock-daily-app-model-discovery"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            errors.append({"source": "huggingface", "query": query, "error": str(exc)})
            continue

        for item in payload:
            model_id = item.get("modelId") or item.get("id")
            if not model_id:
                continue
            hf_url = f"https://huggingface.co/{model_id}"
            tags = item.get("tags") or []
            task_type = item.get("pipeline_tag") or "time_series_or_forecasting"
            candidates.append(
                ModelCandidate(
                    candidate_id=f"hf_{model_id}".lower().replace("/", "_"),
                    model_name=model_id,
                    category="A",
                    source_type="huggingface_search",
                    source_url=hf_url,
                    hf_url=hf_url,
                    has_pretrained_weight=True,
                    weight_url=hf_url,
                    has_training_code=False,
                    has_inference_code=True,
                    data_format_required="model-specific Hugging Face format",
                    input_type="time series windows",
                    output_type="forecast or representation",
                    task_type=task_type,
                    license=next((tag.split("license:")[-1] for tag in tags if str(tag).startswith("license:")), "unknown"),
                    last_update=item.get("lastModified", ""),
                    dependency_risk="unknown",
                    windows_compatibility="unknown",
                    estimated_difficulty="high",
                    priority=75,
                    status="candidate_needs_inspection",
                    notes=f"Hugging Face search result for query: {query}. Tags: {', '.join(map(str, tags[:8]))}",
                )
            )

    return candidates, errors

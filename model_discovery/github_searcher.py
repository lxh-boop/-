from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .model_candidate_schema import ModelCandidate


GITHUB_QUERIES = [
    "stock prediction deep learning pytorch",
    "stock transformer prediction",
    "financial time series forecasting pytorch",
    "OHLCV forecasting transformer",
    "quantitative stock prediction qlib",
    "CSI300 stock prediction",
]


def _github_search_url(query: str, per_page: int = 5) -> str:
    params = urllib.parse.urlencode({
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    return f"https://api.github.com/search/repositories?{params}"


def search_github(per_query: int = 4, timeout: int = 12) -> tuple[list[ModelCandidate], list[dict]]:
    candidates: list[ModelCandidate] = []
    errors: list[dict] = []

    for query in GITHUB_QUERIES:
        url = _github_search_url(query, per_query)
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "stock-daily-app-model-discovery",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            errors.append({"source": "github", "query": query, "error": str(exc)})
            continue

        for item in payload.get("items", []):
            full_name = item.get("full_name", "")
            html_url = item.get("html_url", "")
            if not full_name or not html_url:
                continue
            name = full_name.split("/")[-1]
            candidates.append(
                ModelCandidate(
                    candidate_id=f"github_{full_name}".lower().replace("/", "_"),
                    model_name=name,
                    category="B",
                    source_type="github_search",
                    source_url=html_url,
                    github_url=html_url,
                    has_pretrained_weight=False,
                    has_training_code=True,
                    has_inference_code=True,
                    data_format_required="unknown; inspect repository",
                    input_type="unknown",
                    output_type="unknown",
                    task_type="stock_or_time_series_prediction",
                    license=(item.get("license") or {}).get("spdx_id") or "unknown",
                    stars=int(item.get("stargazers_count") or 0),
                    last_update=item.get("updated_at", ""),
                    dependency_risk="unknown",
                    windows_compatibility="unknown",
                    estimated_difficulty="high",
                    priority=70,
                    status="candidate_needs_inspection",
                    notes=f"GitHub search result for query: {query}. Description: {item.get('description') or ''}",
                )
            )

    return candidates, errors

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .model_candidate_schema import ModelCandidate


ARXIV_QUERIES = [
    "stock prediction transformer",
    "financial time series forecasting",
    "time series foundation model",
]


def search_arxiv(per_query: int = 5, timeout: int = 12) -> tuple[list[ModelCandidate], list[dict]]:
    candidates: list[ModelCandidate] = []
    errors: list[dict] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for query in ARXIV_QUERIES:
        params = urllib.parse.urlencode({
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": per_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        url = f"https://export.arxiv.org/api/query?{params}"
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "stock-daily-app-model-discovery"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8", errors="ignore")
            root = ET.fromstring(payload)
        except Exception as exc:
            errors.append({"source": "arxiv", "query": query, "error": str(exc)})
            continue

        for entry in root.findall("atom:entry", ns):
            title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
            link = entry.findtext("atom:id", default="", namespaces=ns) or ""
            updated = entry.findtext("atom:updated", default="", namespaces=ns) or ""
            if not title or not link:
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:70]
            candidates.append(
                ModelCandidate(
                    candidate_id=f"arxiv_{slug}",
                    model_name=title,
                    category="C",
                    source_type="arxiv",
                    source_url=link,
                    paper_url=link,
                    has_pretrained_weight=False,
                    has_training_code=False,
                    has_inference_code=False,
                    data_format_required="paper only; inspect manually",
                    input_type="unknown",
                    output_type="unknown",
                    task_type="paper_candidate",
                    license="paper",
                    last_update=updated,
                    dependency_risk="unknown",
                    windows_compatibility="unknown",
                    estimated_difficulty="high",
                    priority=90,
                    status="paper_only",
                    notes=f"arXiv search result for query: {query}. Needs code/weight discovery before integration.",
                )
            )

    return candidates, errors

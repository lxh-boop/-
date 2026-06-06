from __future__ import annotations

import argparse
from pathlib import Path

from .candidate_store import (
    dedupe_candidates,
    save_candidates,
    save_errors,
    write_report,
)
from .checkpoint_downloader import record_checkpoint_download_status
from .github_searcher import search_github
from .huggingface_searcher import search_huggingface
from .paper_searcher import search_arxiv
from .repo_downloader import record_repo_download_status
from .train_if_needed import record_training_status
from .web_searcher import seed_candidates


def run_discovery(
    include_online: bool = True,
    github_per_query: int = 4,
    hf_per_query: int = 5,
    arxiv_per_query: int = 4,
    max_candidates: int | None = None,
) -> tuple[list, list[dict]]:
    candidates = seed_candidates()
    errors: list[dict] = []

    if include_online:
        github_candidates, github_errors = search_github(per_query=github_per_query)
        hf_candidates, hf_errors = search_huggingface(per_query=hf_per_query)
        paper_candidates, paper_errors = search_arxiv(per_query=arxiv_per_query)
        candidates.extend(github_candidates)
        candidates.extend(hf_candidates)
        candidates.extend(paper_candidates)
        errors.extend(github_errors + hf_errors + paper_errors)

    candidates = dedupe_candidates(candidates)
    if max_candidates:
        candidates = candidates[: int(max_candidates)]

    save_candidates(candidates)
    save_errors(errors)
    write_report(candidates, errors)
    _record_initial_status(candidates)
    return candidates, errors


def _record_initial_status(candidates: list) -> None:
    for candidate in candidates:
        if candidate.has_pretrained_weight:
            record_checkpoint_download_status(
                candidate,
                status="pending",
                reason="candidate has public or local weight; download/verification not started in discovery step",
            )
        if candidate.github_url and candidate.has_training_code:
            record_repo_download_status(
                candidate,
                status="pending",
                reason="repository clone deferred until candidate is selected for evaluation",
            )
        if candidate.category == "B":
            record_training_status(
                candidate,
                status="pending",
                reason="local training deferred until candidate priority review",
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover candidate stock/time-series models.")
    parser.add_argument("--offline", action="store_true", help="Use curated seed candidates only.")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--github-per-query", type=int, default=4)
    parser.add_argument("--hf-per-query", type=int, default=5)
    parser.add_argument("--arxiv-per-query", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates, errors = run_discovery(
        include_online=not args.offline,
        github_per_query=args.github_per_query,
        hf_per_query=args.hf_per_query,
        arxiv_per_query=args.arxiv_per_query,
        max_candidates=args.max_candidates,
    )
    print(f"[Discovery] candidates={len(candidates)}")
    print(f"[Discovery] errors={len(errors)}")
    print(f"[Discovery] csv={Path('outputs/model_discovery/model_candidates.csv')}")
    if errors:
        print("[Discovery] some online sources failed; see outputs/model_discovery/errors.csv")


if __name__ == "__main__":
    main()

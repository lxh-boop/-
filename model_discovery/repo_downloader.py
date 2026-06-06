from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .candidate_store import DOWNLOAD_LOG_CSV, append_log
from .model_candidate_schema import ModelCandidate


EXTERNAL_REPOS_DIR = Path("external_repos")


def planned_repo_path(candidate: ModelCandidate) -> Path:
    safe_name = candidate.model_name.lower().replace("/", "_").replace(" ", "_")
    return EXTERNAL_REPOS_DIR / safe_name


def record_repo_download_status(candidate: ModelCandidate, status: str, reason: str = "") -> dict:
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_id": candidate.candidate_id,
        "model_name": candidate.model_name,
        "github_url": candidate.github_url,
        "planned_path": str(planned_repo_path(candidate)),
        "status": status,
        "reason": reason,
    }
    append_log(DOWNLOAD_LOG_CSV, row)
    return row

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .candidate_store import TRAIN_LOG_CSV, append_log
from .model_candidate_schema import ModelCandidate


TRAINED_ZOO_DIR = Path("models") / "trained_zoo"


def planned_training_dir(candidate: ModelCandidate) -> Path:
    safe_name = candidate.model_name.lower().replace("/", "_").replace(" ", "_")
    return TRAINED_ZOO_DIR / safe_name / "latest"


def record_training_status(candidate: ModelCandidate, status: str, reason: str = "") -> dict:
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_id": candidate.candidate_id,
        "model_name": candidate.model_name,
        "planned_output_dir": str(planned_training_dir(candidate)),
        "status": status,
        "reason": reason,
    }
    append_log(TRAIN_LOG_CSV, row)
    return row

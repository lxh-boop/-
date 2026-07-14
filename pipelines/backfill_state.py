from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from portfolio.schemas import now_text


@dataclass
class BackfillState:
    user_id: str
    start_date: str
    end_date: str
    last_completed_trade_date: str = ""
    status: str = "pending"
    completed_days: list[str] = field(default_factory=list)
    skipped_days: list[str] = field(default_factory=list)
    failed_days: list[str] = field(default_factory=list)
    current_run_id: str = field(default_factory=lambda: f"backfill_{uuid4().hex[:10]}")
    started_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def backfill_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "portfolio" / str(user_id) / "backfill"


def backfill_state_path(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return backfill_dir(user_id, output_dir) / "backfill_state.json"


def load_backfill_state(user_id: str, output_dir: str | Path = "outputs") -> BackfillState | None:
    path = backfill_state_path(user_id, output_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return BackfillState(**data)


def save_backfill_state(state: BackfillState, output_dir: str | Path = "outputs") -> Path:
    state.updated_at = now_text()
    path = backfill_state_path(state.user_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def backup_backfill_outputs(user_id: str, start_date: str, output_dir: str | Path = "outputs", run_id: str = "") -> Path:
    root = Path(output_dir) / "portfolio" / str(user_id)
    backup = root / "backfill" / "backups" / f"{run_id or uuid4().hex[:8]}_{str(start_date).replace('-', '')}"
    history = root / "history"
    if history.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(history, backup, dirs_exist_ok=True)
    return backup

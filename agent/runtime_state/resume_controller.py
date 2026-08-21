"""Match user supplements to a persisted blocked run."""

from __future__ import annotations

from typing import Any

from .run_checkpoint_store import RunCheckpoint, RunCheckpointStore


class ResumeController:
    def __init__(self, store: RunCheckpointStore) -> None:
        self.store = store

    def match_pending_run(
        self,
        *,
        session_id: str,
        explicit_run_id: str = "",
        supplied_parameters: dict[str, Any] | None = None,
    ) -> RunCheckpoint | None:
        supplied = set(str(key) for key in dict(supplied_parameters or {}))
        candidates = self.store.pending_for_session(session_id)
        if explicit_run_id:
            return next((item for item in candidates if item.run_id == explicit_run_id), None)
        for item in candidates:
            if item.status == "waiting_user_input" and set(item.missing_parameters).intersection(supplied):
                return item
        return None

    def bind_user_supplement(
        self,
        checkpoint: RunCheckpoint,
        supplied_parameters: dict[str, Any],
    ) -> RunCheckpoint:
        supplied = set(str(key) for key in supplied_parameters)
        checkpoint.missing_parameters = [key for key in checkpoint.missing_parameters if key not in supplied]
        if not checkpoint.missing_parameters and not checkpoint.missing_context:
            checkpoint.status = "running"
        return self.store.save(checkpoint)

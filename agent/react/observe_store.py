from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .observe_sanitizer import ObserveSanitizer
from .observation_types import ObservationEvent, ObservationSeverity, ObservationStatus


class ObserveStore:
    def __init__(self, *, output_dir: str | Path = "outputs", sanitizer: ObserveSanitizer | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.root = self.output_dir / "react_logs"
        self.sanitizer = sanitizer or ObserveSanitizer()

    def save_observation(self, observation: ObservationEvent | dict[str, Any], *, user_id: str = "default") -> ObservationEvent:
        event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
        event.status = ObservationStatus.RECORDED
        path = self._path(user_id=user_id, run_id=event.run_id or "no_run")
        path.parent.mkdir(parents=True, exist_ok=True)
        safe = self.sanitizer.sanitize_for_audit(event)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "observation", "observation": safe}, ensure_ascii=False, sort_keys=True) + "\n")
        return ObservationEvent.from_dict(safe)

    def load_observation(self, observation_id: str, *, user_id: str = "default") -> ObservationEvent | None:
        observation_id = str(observation_id or "")
        for event in self._iter_observations(user_id=user_id):
            if event.observation_id == observation_id:
                return event
        return None

    def list_observations_by_run(self, run_id: str, *, user_id: str = "default") -> list[ObservationEvent]:
        path = self._path(user_id=user_id, run_id=str(run_id or "no_run"))
        return self._read_file(path)

    def list_observations_by_conversation(self, conversation_id: str, *, user_id: str = "default") -> list[ObservationEvent]:
        conversation_id = str(conversation_id or "")
        return [event for event in self._iter_observations(user_id=user_id) if event.conversation_id == conversation_id]

    def list_observations_by_task(self, task_id: str, *, user_id: str = "default", run_id: str = "") -> list[ObservationEvent]:
        task_id = str(task_id or "")
        source = self.list_observations_by_run(run_id, user_id=user_id) if run_id else list(self._iter_observations(user_id=user_id))
        return [event for event in source if event.task_id == task_id]

    def list_blocking_observations(self, *, user_id: str = "default", run_id: str = "") -> list[ObservationEvent]:
        source = self.list_observations_by_run(run_id, user_id=user_id) if run_id else list(self._iter_observations(user_id=user_id))
        return [event for event in source if event.severity == ObservationSeverity.BLOCKING]

    def expire_observations(
        self,
        *,
        user_id: str = "default",
        run_id: str = "",
        observation_ids: list[str] | None = None,
    ) -> int:
        ids = {str(item) for item in (observation_ids or []) if str(item).strip()}
        paths = [self._path(user_id=user_id, run_id=run_id)] if run_id else sorted((self.root / str(user_id or "default")).glob("*.jsonl"))
        changed = 0
        for path in paths:
            events = self._read_file(path)
            if not events:
                continue
            rows = []
            file_changed = False
            for event in events:
                if not ids or event.observation_id in ids:
                    event.status = ObservationStatus.EXPIRED
                    changed += 1
                    file_changed = True
                rows.append(event)
            if file_changed:
                self._rewrite_file(path, rows)
        return changed

    def _path(self, *, user_id: str, run_id: str) -> Path:
        safe_user = str(user_id or "default").replace("\\", "_").replace("/", "_")
        safe_run = str(run_id or "no_run").replace("\\", "_").replace("/", "_")
        return self.root / safe_user / f"{safe_run}.jsonl"

    def _iter_observations(self, *, user_id: str = "default") -> list[ObservationEvent]:
        base = self.root / str(user_id or "default")
        if not base.exists():
            return []
        events: list[ObservationEvent] = []
        for path in sorted(base.glob("*.jsonl")):
            events.extend(self._read_file(path))
        return events

    @staticmethod
    def _read_file(path: Path) -> list[ObservationEvent]:
        if not path.exists():
            return []
        events: list[ObservationEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("observation") if isinstance(row, dict) else None
                if isinstance(payload, dict):
                    events.append(ObservationEvent.from_dict(payload))
        return events

    def _rewrite_file(self, path: Path, events: list[ObservationEvent]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                safe = self.sanitizer.sanitize_for_audit(event)
                handle.write(json.dumps({"kind": "observation", "observation": safe}, ensure_ascii=False, sort_keys=True) + "\n")

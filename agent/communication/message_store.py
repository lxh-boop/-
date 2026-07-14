from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.communication.message_sanitizer import MessageSanitizer
from agent.communication.message_trace import MessageTrace, build_message_trace
from agent.communication.message_types import AgentMessage


class MessageStore:
    def __init__(self, *, output_dir: str | Path = "outputs", sanitizer: MessageSanitizer | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.sanitizer = sanitizer or MessageSanitizer()

    def save_message(self, message: AgentMessage | dict[str, Any]) -> AgentMessage:
        safe_message = self._safe_message(message)
        path = self._path_for(safe_message)
        path.parent.mkdir(parents=True, exist_ok=True)
        if safe_message.message_id in self._message_ids(path):
            return safe_message
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "message", "message": safe_message.to_dict()}, ensure_ascii=False) + "\n")
        return safe_message

    def load_message(self, message_id: str, *, run_id: str = "", conversation_id: str = "", user_id: str = "default") -> AgentMessage | None:
        for message in self._iter_candidate_messages(run_id=run_id, conversation_id=conversation_id, user_id=user_id):
            if message.message_id == str(message_id):
                return message
        return None

    def list_messages_by_run(self, run_id: str, *, user_id: str = "default") -> list[AgentMessage]:
        return [message for message in self._read_messages(self._path_for_run(user_id, run_id)) if message.run_id == str(run_id)]

    def list_messages_by_conversation(self, conversation_id: str, *, user_id: str = "default") -> list[AgentMessage]:
        return [
            message
            for message in self._iter_candidate_messages(run_id="", conversation_id=conversation_id, user_id=user_id)
            if message.conversation_id == str(conversation_id)
        ]

    def list_messages_by_task(self, task_id: str, *, run_id: str = "", user_id: str = "default") -> list[AgentMessage]:
        messages = self._iter_candidate_messages(run_id=run_id, conversation_id="", user_id=user_id)
        return [message for message in messages if message.task_id == str(task_id)]

    def append_trace_event(self, trace: MessageTrace | dict[str, Any], *, user_id: str = "default", run_id: str = "") -> dict[str, Any]:
        payload = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace or {})
        safe_payload = self.sanitizer.sanitize_for_audit(payload)
        target_run_id = str(run_id or safe_payload.get("run_id") or "no_run")
        path = self._path_for_run(user_id, target_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "trace", "trace": safe_payload}, ensure_ascii=False) + "\n")
        return safe_payload

    def expire_messages(self, *, run_id: str, user_id: str = "default") -> int:
        path = self._path_for_run(user_id, run_id)
        if not path.exists():
            return 0
        expired = 0
        retained: list[dict[str, Any]] = []
        for record in self._read_records(path):
            if record.get("kind") == "message":
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                message["status"] = "EXPIRED"
                record["message"] = message
                expired += 1
            retained.append(record)
        with path.open("w", encoding="utf-8") as handle:
            for record in retained:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return expired

    def build_trace(self, run_id: str, *, user_id: str = "default", trace_id: str = "") -> MessageTrace:
        return build_message_trace(self.list_messages_by_run(run_id, user_id=user_id), trace_id=trace_id)

    def _safe_message(self, message: AgentMessage | dict[str, Any]) -> AgentMessage:
        raw = message if isinstance(message, AgentMessage) else AgentMessage.from_dict(dict(message or {}))
        safe = self.sanitizer.sanitize_for_audit(raw)
        return AgentMessage.from_dict(safe)

    def _path_for(self, message: AgentMessage) -> Path:
        user_id = str(message.metadata.get("user_id") or message.payload.get("user_id") or "default")
        run_id = str(message.run_id or message.payload.get("run_id") or "no_run")
        return self._path_for_run(user_id, run_id)

    def _path_for_run(self, user_id: str, run_id: str) -> Path:
        safe_user = _safe_path_part(user_id or "default")
        safe_run = _safe_path_part(run_id or "no_run")
        return self.output_dir / "message_logs" / safe_user / f"{safe_run}.jsonl"

    def _iter_candidate_messages(self, *, run_id: str = "", conversation_id: str = "", user_id: str = "default") -> list[AgentMessage]:
        if run_id:
            return self._read_messages(self._path_for_run(user_id, run_id))
        base = self.output_dir / "message_logs" / _safe_path_part(user_id or "default")
        if not base.exists():
            return []
        messages: list[AgentMessage] = []
        for path in sorted(base.glob("*.jsonl")):
            messages.extend(self._read_messages(path))
        if conversation_id:
            return [message for message in messages if message.conversation_id == str(conversation_id)]
        return messages

    def _read_messages(self, path: Path) -> list[AgentMessage]:
        messages: list[AgentMessage] = []
        for record in self._read_records(path):
            if record.get("kind") != "message":
                continue
            payload = record.get("message")
            if isinstance(payload, dict):
                try:
                    messages.append(AgentMessage.from_dict(payload))
                except Exception:
                    continue
        return messages

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    @staticmethod
    def _message_ids(path: Path) -> set[str]:
        return {
            str((record.get("message") or {}).get("message_id") or "")
            for record in MessageStore._read_records(path)
            if isinstance(record.get("message"), dict)
        }


def _safe_path_part(value: str) -> str:
    text = str(value or "default")
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)[:120] or "default"


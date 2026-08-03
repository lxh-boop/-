"""Persist inspectable LLM request snapshots without affecting model execution."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "passwd",
    "secret",
    "token",
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_LONG_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)")
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_name(value: Any, fallback: str) -> str:
    text = _SAFE_NAME_PATTERN.sub("_", str(value or "").strip()).strip("._-")
    return (text[:96] or fallback)


def _estimate_tokens(text: str) -> int:
    """Return a tokenizer-free estimate suitable only for section comparison."""

    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key or "").strip().lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _redact_plain_text(value: str) -> str:
    text = _BEARER_PATTERN.sub("Bearer <redacted>", str(value or ""))
    return _LONG_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def _redact(value: Any, *, key: str = "") -> Any:
    if key and _is_sensitive_key(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): _redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_plain_text(value)
    return value



def _redact_message(message: dict[str, Any]) -> dict[str, Any]:
    copied = {str(key): value for key, value in dict(message).items()}
    content = copied.get("content")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            copied["content"] = _redact_plain_text(content)
        else:
            copied["content"] = json.dumps(
                _redact(parsed),
                ensure_ascii=False,
                separators=(",", ":"),
            )
    else:
        copied["content"] = _redact(content)
    return _redact(copied)

def _stats(text: str) -> dict[str, int]:
    return {
        "chars": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "estimated_tokens": _estimate_tokens(text),
    }


def _json_sections(content: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict):
        return []
    sections: list[dict[str, Any]] = []
    for key, value in parsed.items():
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        sections.append({"name": str(key), **_stats(rendered)})
    sections.sort(key=lambda item: int(item["utf8_bytes"]), reverse=True)
    return sections


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _dump_root() -> Path:
    configured = str(os.environ.get("STOCK_LLM_PROMPT_DUMP_DIR") or "").strip()
    root = Path(configured or "outputs/llm_prompt_dumps")
    return root if root.is_absolute() else Path.cwd() / root


@dataclass(frozen=True)
class PromptDumpHandle:
    dump_id: str
    json_path: Path
    markdown_path: Path
    document: dict[str, Any]


def start_prompt_dump(
    *,
    stage: str,
    operation: str,
    profile: Any,
    messages: list[dict[str, Any]],
    temperature: float,
    max_output_tokens: int,
) -> PromptDumpHandle | None:
    """Write a request snapshot before network I/O.

    Errors are swallowed by callers so observability never blocks the LLM call.
    """

    dump_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    task_id = _safe_name(os.environ.get("STOCK_AGENT_TASK_ID"), "unbound_task")
    stage_name = _safe_name(stage, "unknown_stage")
    operation_name = _safe_name(operation, "primary")
    directory = _dump_root() / task_id
    stem = f"{timestamp}_{stage_name}_{operation_name}_{dump_id[:8]}"

    redacted_messages = [_redact_message(dict(item)) for item in messages]
    message_rows: list[dict[str, Any]] = []
    total_chars = 0
    total_bytes = 0
    total_estimated = 0
    for index, item in enumerate(redacted_messages):
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        stats = _stats(content)
        total_chars += stats["chars"]
        total_bytes += stats["utf8_bytes"]
        total_estimated += stats["estimated_tokens"]
        message_rows.append(
            {
                "index": index,
                "role": role,
                **stats,
                "json_sections": _json_sections(content),
            }
        )

    document: dict[str, Any] = {
        "schema_version": 1,
        "dump_id": dump_id,
        "status": "started",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "task_id": str(os.environ.get("STOCK_AGENT_TASK_ID") or ""),
        "process_id": os.getpid(),
        "stage": str(stage or ""),
        "operation": str(operation or "primary"),
        "request": {
            "temperature": float(temperature),
            "max_output_tokens": max(1, int(max_output_tokens)),
            "message_count": len(redacted_messages),
            "messages": redacted_messages,
        },
        "profile": {
            "profile_id": str(getattr(profile, "profile_id", "") or ""),
            "config_hash": str(getattr(profile, "config_hash", "") or ""),
            "deployment_mode": str(getattr(profile, "deployment_mode", "") or ""),
            "provider_id": str(getattr(profile, "provider_id", "") or ""),
            "model_name": str(getattr(profile, "model_name", "") or ""),
            "base_url": str(getattr(profile, "base_url", "") or ""),
            "endpoint_scope": str(getattr(profile, "endpoint_scope", "") or ""),
            "context_window": int(getattr(profile, "context_window", 0) or 0),
        },
        "analysis": {
            "messages": message_rows,
            "total_chars": total_chars,
            "total_utf8_bytes": total_bytes,
            "total_estimated_tokens": total_estimated,
            "estimate_method": "ceil(utf8_bytes/4); comparison aid only",
            "actual_usage": {},
        },
        "response": {},
        "error": {},
    }

    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    _write_document(json_path, markdown_path, document)
    return PromptDumpHandle(dump_id=dump_id, json_path=json_path, markdown_path=markdown_path, document=document)


def finish_prompt_dump(
    handle: PromptDumpHandle | None,
    *,
    response: Any | None = None,
    error: Exception | None = None,
) -> None:
    if handle is None:
        return
    document = dict(handle.document)
    document["updated_at"] = _utc_now()
    if error is not None:
        document["status"] = "failed"
        document["error"] = {
            "error_type": type(error).__name__,
            "message": _redact_plain_text(str(error))[:2000],
        }
    elif response is not None:
        usage = dict(getattr(response, "usage", {}) or {})
        document["status"] = "completed"
        document["analysis"] = {
            **dict(document.get("analysis") or {}),
            "actual_usage": {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
        }
        content = str(getattr(response, "content", "") or "")
        document["response"] = {
            "provider_request_id": str(getattr(response, "provider_request_id", "") or ""),
            "content_chars": len(content),
            "content_excerpt": _redact_plain_text(content[:2000]),
        }
    _write_document(handle.json_path, handle.markdown_path, document)


def _write_document(json_path: Path, markdown_path: Path, document: dict[str, Any]) -> None:
    _atomic_write(json_path, json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n")

    analysis = dict(document.get("analysis") or {})
    profile = dict(document.get("profile") or {})
    lines = [
        "# LLM Prompt Dump",
        "",
        f"- Dump ID: `{document.get('dump_id', '')}`",
        f"- Status: `{document.get('status', '')}`",
        f"- Task ID: `{document.get('task_id', '') or 'unbound'}`",
        f"- Stage: `{document.get('stage', '')}`",
        f"- Operation: `{document.get('operation', '')}`",
        f"- Mode: `{profile.get('deployment_mode', '')}`",
        f"- Provider: `{profile.get('provider_id', '')}`",
        f"- Model: `{profile.get('model_name', '')}`",
        f"- Config hash: `{profile.get('config_hash', '')}`",
        f"- Estimated input tokens: `{analysis.get('total_estimated_tokens', 0)}`",
        f"- Actual prompt tokens: `{dict(analysis.get('actual_usage') or {}).get('prompt_tokens', 0)}`",
        "",
        "## Message and section sizes",
        "",
        "| Message | Role | Chars | UTF-8 bytes | Estimated tokens |",
        "|---:|---|---:|---:|---:|",
    ]
    for item in analysis.get("messages") or []:
        lines.append(
            f"| {item.get('index')} | {item.get('role')} | {item.get('chars')} | "
            f"{item.get('utf8_bytes')} | {item.get('estimated_tokens')} |"
        )
        sections = item.get("json_sections") or []
        if sections:
            lines.extend(["", f"### Message {item.get('index')} JSON sections", "", "| Section | Chars | UTF-8 bytes | Estimated tokens |", "|---|---:|---:|---:|"])
            for section in sections:
                lines.append(
                    f"| `{section.get('name')}` | {section.get('chars')} | "
                    f"{section.get('utf8_bytes')} | {section.get('estimated_tokens')} |"
                )
    lines.extend(["", "## Full request messages", ""])
    for index, message in enumerate(dict(document.get("request") or {}).get("messages") or []):
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        lines.extend([f"### Message {index}: {role}", "", "```text", content, "```", ""])
    if document.get("error"):
        lines.extend(["## Error", "", "```json", json.dumps(document.get("error"), ensure_ascii=False, indent=2), "```", ""])
    _atomic_write(markdown_path, "\n".join(lines).rstrip() + "\n")


__all__ = ["PromptDumpHandle", "finish_prompt_dump", "start_prompt_dump"]

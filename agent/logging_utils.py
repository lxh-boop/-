from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config.paths import LOGS_DIR


AGENT_LOG_PATH = LOGS_DIR / "agent_calls.jsonl"


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token)['\"]?\s*[:=]\s*['\"]?[^,'\"\s}]+"),
]


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


def log_agent_call(
    *,
    query: str,
    intent: str,
    tool_name: str,
    tool_args: dict[str, Any],
    success: bool,
    message: str,
    result_preview: str = "",
) -> Path:
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": _sanitize(query),
        "intent": intent,
        "tool_name": tool_name,
        "tool_args": _sanitize(tool_args),
        "success": bool(success),
        "message": _sanitize(message),
        "result_preview": _sanitize(result_preview),
    }
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return AGENT_LOG_PATH


def read_recent_agent_logs(limit: int = 20) -> list[dict]:
    if not AGENT_LOG_PATH.exists():
        return []
    lines = AGENT_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows = []
    for line in lines[-max(1, int(limit)) :]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows

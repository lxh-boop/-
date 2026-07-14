from __future__ import annotations

import contextvars
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid


_CURRENT_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_flow_current_run_id",
    default="",
)

_LOCK = threading.RLock()
_RUN_FILES: dict[str, Path] = {}
_RUN_SEQUENCE: dict[str, int] = {}

_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|token|secret|password|passwd|credential|"
    r"confirmation[_-]?token|tushare[_-]?token)",
    flags=re.IGNORECASE,
)
_PATH_KEY_PATTERN = re.compile(
    r"(?:db[_-]?path|database[_-]?path|file[_-]?path|local[_-]?path|"
    r"absolute[_-]?path|stack[_-]?trace|traceback|raw[_-]?payload)",
    flags=re.IGNORECASE,
)
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?:[A-Z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]*)"
)
_SECRET_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|confirmation[_-]?token)"
        r"\s*[:=：]\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
)

_STAGE_LABELS = {
    "REQUEST": "用户请求",
    "CONTEXT": "上下文构建",
    "RULE_HINTS": "规则提示",
    "LLM_USER_GOAL": "用户目标识别",
    "GOAL_REVIEW": "目标审查",
    "TASK_PLAN": "任务计划",
    "PLAN_REVIEW": "计划审查",
    "SAFETY_VALIDATION": "安全校验",
    "TASK_PLAN_EXECUTION": "任务计划执行",
    "TASK_START": "任务开始",
    "TASK_RESULT": "任务结果",
    "COMPLETION_OBSERVE": "完成度观察",
    "OBSERVATION": "执行观察",
    "REPLAN": "重新规划",
    "REPORT": "回答生成",
    "FINAL_REPORT": "最终回答",
    "CRITIC": "结果审查",
    "UI": "页面输出",
    "EXCEPTION": "异常记录",
}


def _env_truthy(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def flow_trace_enabled() -> bool:
    """Whether the human-readable Agent flow document is enabled."""
    return _env_truthy("AGENT_FLOW_TRACE", default=True)


def console_trace_enabled() -> bool:
    """Whether dense technical trace events should enter the Markdown."""
    return _env_truthy("AGENT_CONSOLE_TRACE", default=False)


is_flow_trace_enabled = flow_trace_enabled
is_console_trace_enabled = console_trace_enabled


def _max_chars() -> int:
    raw = os.getenv("AGENT_FLOW_TRACE_MAX_CHARS", "30000")
    try:
        return max(2000, min(int(raw), 200000))
    except (TypeError, ValueError):
        return 30000


def _max_depth() -> int:
    raw = os.getenv("AGENT_FLOW_TRACE_MAX_DEPTH", "8")
    try:
        return max(2, min(int(raw), 20))
    except (TypeError, ValueError):
        return 8


def _redact_text(value: str) -> str:
    text = str(value or "")
    text = _WINDOWS_PATH_PATTERN.sub("[redacted local path]", text)

    for pattern in _SECRET_TEXT_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(
                lambda match: f"{match.group(1)}=[redacted]",
                text,
            )
        else:
            text = pattern.sub("[redacted secret]", text)

    if "traceback (most recent call last)" in text.lower():
        return "[redacted internal traceback]"
    return text


def sanitize_for_trace(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-safe, bounded and redacted trace payload."""
    if depth > _max_depth():
        return "<max_depth>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        text = _redact_text(value)
        limit = _max_chars()
        return text if len(text) <= limit else text[:limit] + "\n...[truncated]"

    if isinstance(value, Path):
        return "[redacted local path]"

    if isinstance(value, BaseException):
        return {
            "exception_type": type(value).__name__,
            "message": _redact_text(str(value)),
        }

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 200:
                result["..."] = "<remaining keys truncated>"
                break

            key = str(raw_key)
            if _SECRET_KEY_PATTERN.search(key):
                result[key] = "[redacted secret]"
                continue
            if _PATH_KEY_PATTERN.search(key):
                result[key] = "[redacted internal value]"
                continue

            result[key] = sanitize_for_trace(item, depth=depth + 1)
        return result

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [
            sanitize_for_trace(item, depth=depth + 1)
            for item in items[:200]
        ]
        if len(items) > 200:
            result.append(f"<{len(items) - 200} more items truncated>")
        return result

    if hasattr(value, "to_dict"):
        try:
            return sanitize_for_trace(value.to_dict(), depth=depth + 1)
        except Exception:
            pass

    return _redact_text(str(value))


sanitize_trace_payload = sanitize_for_trace
safe_trace_payload = sanitize_for_trace
redact_trace_payload = sanitize_for_trace


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(
            sanitize_for_trace(value),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    except Exception:
        return json.dumps(
            {"value": _redact_text(str(value))},
            ensure_ascii=False,
            indent=2,
        )


def _safe_file_name(value: str) -> str:
    """Keep Chinese, letters and numbers while removing Windows-invalid chars."""
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", str(value or ""))
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    if not text:
        text = "agent_response"

    # Avoid Windows reserved basenames.
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if text.upper() in reserved:
        text = f"_{text}"
    return text[:120]


def _extract_question_text(payload: Any, *, depth: int = 0) -> str:
    if depth > 5:
        return ""

    if isinstance(payload, dict):
        for key in (
            "query",
            "question",
            "raw_message",
            "user_query",
            "message",
            "prompt",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in payload.values():
            found = _extract_question_text(value, depth=depth + 1)
            if found:
                return found

    elif isinstance(payload, (list, tuple)):
        for value in payload[:20]:
            found = _extract_question_text(value, depth=depth + 1)
            if found:
                return found

    elif isinstance(payload, str):
        return payload.strip()

    return ""


def _question_filename_stem(question: str) -> str:
    """Use the first ten words; continuous Chinese falls back to ten characters."""
    text = re.sub(r"\s+", " ", str(question or "").strip())
    if not text:
        return "agent_response"

    if " " in text:
        words = re.findall(r"[\w\u4e00-\u9fff]+", text, flags=re.UNICODE)[:10]
        stem = "_".join(words)
    elif re.search(r"[\u4e00-\u9fff]", text):
        # No word segmenter dependency is introduced. Ignore punctuation and
        # take the first ten visible Chinese/letter/number characters.
        units = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)[:10]
        stem = "".join(units)
    else:
        words = re.findall(r"[A-Za-z0-9._-]+", text)[:10]
        stem = "_".join(words)

    return _safe_file_name(stem or "agent_response")


def _output_directory() -> Path:
    configured = str(os.getenv("AGENT_FLOW_MARKDOWN_DIR", "")).strip()
    path = Path(configured) if configured else Path.cwd() / "outputs" / "agent_flow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _deduplicated_markdown_path(stem: str) -> Path:
    directory = _output_directory()
    candidate = directory / f"{stem}.md"
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = directory / f"{stem}_{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def _find_identifier(
    payload: Any,
    names: tuple[str, ...],
    *,
    depth: int = 0,
) -> str:
    if depth > 5:
        return ""

    if isinstance(payload, dict):
        for name in names:
            value = payload.get(name)
            if value not in (None, ""):
                return str(value)

        for value in payload.values():
            found = _find_identifier(value, names, depth=depth + 1)
            if found:
                return found

    elif isinstance(payload, (list, tuple)):
        for value in payload[:30]:
            found = _find_identifier(value, names, depth=depth + 1)
            if found:
                return found

    return ""


def _new_fallback_run_id() -> str:
    return (
        "agent_flow_"
        + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        + "_"
        + uuid.uuid4().hex[:8]
    )


def _resolve_run_id(stage: str, payload: Any, explicit_run_id: str = "") -> str:
    stage_name = str(stage or "").strip().upper()
    discovered = (
        str(explicit_run_id or "").strip()
        or _find_identifier(payload, ("run_id", "agent_run_id"))
    )
    current = _CURRENT_RUN_ID.get()

    if stage_name == "REQUEST":
        run_id = discovered or _new_fallback_run_id()
        _CURRENT_RUN_ID.set(run_id)
        return run_id

    if discovered:
        if current and current != discovered:
            _adopt_run_id(current, discovered)
        _CURRENT_RUN_ID.set(discovered)
        return discovered

    if current:
        return current

    run_id = _new_fallback_run_id()
    _CURRENT_RUN_ID.set(run_id)
    return run_id


def _adopt_run_id(old_run_id: str, new_run_id: str) -> None:
    with _LOCK:
        old_path = _RUN_FILES.get(old_run_id)
        new_path = _RUN_FILES.get(new_run_id)
        if old_path is None or not old_path.exists():
            return

        if new_path is None:
            _RUN_FILES[new_run_id] = old_path
            _RUN_SEQUENCE[new_run_id] = _RUN_SEQUENCE.get(old_run_id, 0)
            _RUN_FILES.pop(old_run_id, None)
            _RUN_SEQUENCE.pop(old_run_id, None)
            return

        try:
            old_content = old_path.read_text(encoding="utf-8")
            with new_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n\n# 合并的早期流程\n\n")
                handle.write(old_content)
            old_path.unlink(missing_ok=True)
        except OSError:
            return


def _write_document_header(path: Path, run_id: str, *, question: str = "") -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    lines = [
        "> Agent 单次响应工作流程",
        ">",
        f"> Run ID：`{_redact_text(run_id)}`",
    ]
    if question:
        lines.extend([">", f"> 问题：`{_redact_text(question)}`"])
    lines.extend([">", f"> 创建时间：`{created_at}`", "", "---", ""])
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _path_for_run(
    run_id: str,
    *,
    start_new: bool,
    payload: Any = None,
) -> Path:
    with _LOCK:
        if start_new or run_id not in _RUN_FILES:
            question = _extract_question_text(payload)
            stem = _question_filename_stem(question)
            path = _deduplicated_markdown_path(stem)
            _RUN_FILES[run_id] = path
            _RUN_SEQUENCE[run_id] = 0
            _write_document_header(path, run_id, question=question)
        return _RUN_FILES[run_id]


def _normalise_event_arguments(
    payload: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[Any, str, str, str, dict[str, Any]]:
    event_payload = payload
    remaining = list(args)
    if event_payload is None and remaining:
        event_payload = remaining.pop(0)

    run_id = str(
        kwargs.pop("run_id", "")
        or kwargs.pop("agent_run_id", "")
        or ""
    )
    task_id = str(kwargs.pop("task_id", "") or "")
    level = str(kwargs.pop("level", "INFO") or "INFO")

    metadata = dict(kwargs)
    if remaining:
        metadata["extra_args"] = remaining

    return event_payload, run_id, task_id, level, metadata


def _append_event(
    *,
    stage: str,
    payload: Any,
    run_id: str,
    task_id: str,
    level: str,
    metadata: dict[str, Any],
    trace_kind: str,
) -> str:
    stage_name = str(stage or "UNKNOWN").strip()
    stage_upper = stage_name.upper()
    canonical_run_id = _resolve_run_id(stage_upper, payload, run_id)
    start_new = stage_upper == "REQUEST"

    with _LOCK:
        path = _path_for_run(
            canonical_run_id,
            start_new=start_new,
            payload=payload,
        )
        sequence = _RUN_SEQUENCE.get(canonical_run_id, 0) + 1
        _RUN_SEQUENCE[canonical_run_id] = sequence

        title_label = _STAGE_LABELS.get(stage_upper, stage_name)
        details = [
            f"# {sequence:02d} · {stage_upper} · {title_label}",
            "",
            f"- 时间：`{datetime.now().isoformat(timespec='milliseconds')}`",
            f"- 类型：`{trace_kind}`",
            f"- 级别：`{_redact_text(level)}`",
        ]
        if task_id:
            details.append(f"- Task ID：`{_redact_text(task_id)}`")

        combined_payload: Any = payload
        if metadata:
            combined_payload = {"payload": payload, "metadata": metadata}

        details.extend(
            [
                "",
                "```json",
                safe_json_dumps(combined_payload),
                "```",
                "",
                "---",
                "",
            ]
        )

        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(details))

    return str(path)


def flow_event(
    stage: str,
    payload: Any = None,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Append a major Agent step to this response's Markdown document."""
    if not flow_trace_enabled():
        return ""

    event_payload, run_id, task_id, level, metadata = _normalise_event_arguments(
        payload,
        args,
        kwargs,
    )
    try:
        return _append_event(
            stage=stage,
            payload=event_payload,
            run_id=run_id,
            task_id=task_id,
            level=level,
            metadata=metadata,
            trace_kind="AGENT-FLOW",
        )
    except Exception:
        return ""


def trace_event(
    stage: str,
    payload: Any = None,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Append an optional dense technical event to the same Markdown."""
    if not console_trace_enabled():
        return ""

    event_payload, run_id, task_id, level, metadata = _normalise_event_arguments(
        payload,
        args,
        kwargs,
    )
    try:
        return _append_event(
            stage=f"TRACE · {stage}",
            payload=event_payload,
            run_id=run_id,
            task_id=task_id,
            level=level,
            metadata=metadata,
            trace_kind="AGENT-TRACE",
        )
    except Exception:
        return ""


def trace_exception(
    stage_or_exception: Any = None,
    exception: BaseException | None = None,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Record an exception without exposing traceback or local paths.

    Compatible call forms include::

        trace_exception("ai_agent.run", exc)
        trace_exception(exc, stage="ai_agent.run")
        trace_exception(stage="ai_agent.run", exception=exc)

    Exception records are treated as major flow events, so they are written
    even when ``AGENT_CONSOLE_TRACE=0``.
    """
    stage_kw = str(
        kwargs.pop("stage", "")
        or kwargs.pop("event", "")
        or kwargs.pop("name", "")
        or ""
    )
    exc_kw = kwargs.pop("exc", None) or kwargs.pop("error", None)

    stage = stage_kw
    exc: BaseException | None = None

    if isinstance(stage_or_exception, BaseException):
        exc = stage_or_exception
    elif stage_or_exception not in (None, ""):
        stage = str(stage_or_exception)

    if isinstance(exception, BaseException):
        exc = exception
    elif exception not in (None, ""):
        # Preserve non-exception second arguments as safe context.
        kwargs.setdefault("exception_context", exception)

    if isinstance(exc_kw, BaseException):
        exc = exc_kw
    elif exc_kw not in (None, ""):
        kwargs.setdefault("error_context", exc_kw)

    if not stage:
        stage = type(exc).__name__ if exc is not None else "EXCEPTION"

    payload: dict[str, Any] = {
        "stage": stage,
        "exception_type": type(exc).__name__ if exc is not None else "Exception",
        "message": _redact_text(str(exc)) if exc is not None else "",
    }
    if args:
        payload["context"] = list(args)
    if kwargs:
        payload["metadata"] = kwargs

    return flow_event(
        f"EXCEPTION · {stage}",
        payload,
        level="ERROR",
    )


def get_flow_markdown_path(run_id: str | None = None) -> str:
    target = str(run_id or "").strip() or _CURRENT_RUN_ID.get()
    path = _RUN_FILES.get(target)
    return str(path) if path is not None else ""


def reset_flow_context() -> None:
    _CURRENT_RUN_ID.set("")


console_event = trace_event
agent_trace = trace_event
emit_trace = trace_event
emit_flow = flow_event
trace = trace_event
flow = flow_event

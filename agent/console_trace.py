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
_RUN_FINALIZED: set[str] = set()
_RUN_TOOL_EXECUTIONS: dict[str, list[dict[str, Any]]] = {}

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
    "GRAPH_RUNTIME_INITIALIZATION_STARTED": "金融图运行时初始化开始",
    "GRAPH_RUNTIME_INITIALIZATION_COMPLETED": "金融图运行时初始化完成",
    "GRAPH_RUNTIME_INITIALIZATION_FAILED": "金融图运行时初始化失败",
    "MAIN_ENTRY_DECISION_STARTED": "MainAgent 入口判断开始",
    "MAIN_ENTRY_DECISION_COMPLETED": "MainAgent 入口判断完成",
    "GRAPH_REF_RESOLUTION_STARTED": "GraphRef 解析开始",
    "GRAPH_REF_RESOLUTION_COMPLETED": "GraphRef 解析完成",
    "WORKER_PLANNING_STARTED": "Worker DAG 规划开始",
    "LOCAL_LLM_REQUEST_STARTED": "本地模型规划请求开始",
    "LOCAL_LLM_RESPONSE_RECEIVED": "本地模型规划响应已返回",
    "WORKER_PLAN_CANDIDATE_GENERATED": "候选 Worker DAG 已生成",
    "WORKER_PLAN_VALIDATION_FAILED": "候选 Worker DAG 校验失败",
    "WORKER_PLAN_REPAIR_STARTED": "完整 Worker DAG 重新规划开始",
    "WORKER_PLAN_REPAIR_RESPONSE_RECEIVED": "重新规划响应已返回",
    "WORKER_PLAN_REPAIR_CANDIDATE_GENERATED": "重新规划候选 DAG 已生成",
    "WORKER_PLAN_REPAIR_SUCCEEDED": "重新规划通过",
    "WORKER_PLAN_REPAIR_FAILED": "重新规划失败",
    "WORKER_PLAN_ACCEPTED": "Worker DAG 候选已接受",
    "WORKER_DAG_VALIDATED": "Worker DAG 合同校验通过",
    "WORKER_PLANNING_COMPLETED": "Worker DAG 规划完成",
    "WORKER_PLANNING_FAILED": "Worker DAG 规划失败",
    "WORKER_DAG_REGISTERED": "Worker DAG 已登记",
    "WORKER_EXECUTION_STARTED": "Worker DAG 执行开始",
    "WORKER_EXECUTION_COMPLETED": "Worker DAG 执行完成",
    "TOOL_EXECUTION_STARTED": "工具执行开始",
    "TOOL_EXECUTION_SUCCEEDED": "工具执行成功",
    "TOOL_EXECUTION_FAILED": "工具执行失败",
    "TOOL_EXECUTION_BLOCKED": "工具执行被阻止",
    "RUN_FAILED": "Agent Run 失败",
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
            question_stem = _question_filename_stem(question)
            run_stem = _safe_file_name(run_id or _new_fallback_run_id())
            path = _output_directory() / f"{question_stem}__{run_stem}.md"
            _RUN_FILES[run_id] = path
            _RUN_SEQUENCE[run_id] = 0
            if not path.exists():
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


def record_tool_execution(
    *,
    run_id: str,
    task_id: str,
    tool_call_id: str,
    tool_name: str,
    canonical_tool_name: str = "",
    status: str,
    success: bool,
    started_at: str = "",
    finished_at: str = "",
    duration_ms: float = 0.0,
    argument_keys: list[str] | None = None,
    error_type: str = "",
    error_message: str = "",
    failure_kind: str = "",
    retryable: bool = False,
    warning_count: int = 0,
    error_count: int = 0,
    artifact_id: str = "",
    retry_count: int = 0,
    circuit_state: str = "",
) -> str:
    """Persist one terminal tool-call status without raw arguments or responses."""
    canonical_run_id = str(run_id or "").strip()
    if not canonical_run_id:
        return ""
    normalized_status = str(status or ("succeeded" if success else "failed")).lower()
    record = {
        "tool_call_id": str(tool_call_id or ""),
        "task_id": str(task_id or ""),
        "tool_name": str(tool_name or ""),
        "canonical_tool_name": str(canonical_tool_name or tool_name or ""),
        "status": normalized_status,
        "success": bool(success),
        "started_at": str(started_at or ""),
        "finished_at": str(finished_at or ""),
        "duration_ms": float(duration_ms or 0.0),
        "argument_keys": list(argument_keys or []),
        "error_type": str(error_type or ""),
        "error_message": str(error_message or ""),
        "failure_kind": str(failure_kind or ""),
        "retryable": bool(retryable),
        "warning_count": int(warning_count or 0),
        "error_count": int(error_count or 0),
        "artifact_id": str(artifact_id or ""),
        "retry_count": int(retry_count or 0),
        "circuit_state": str(circuit_state or ""),
    }
    with _LOCK:
        _RUN_TOOL_EXECUTIONS.setdefault(canonical_run_id, []).append(record)
    stage = {
        "succeeded": "TOOL_EXECUTION_SUCCEEDED",
        "completed": "TOOL_EXECUTION_SUCCEEDED",
        "blocked": "TOOL_EXECUTION_BLOCKED",
    }.get(normalized_status, "TOOL_EXECUTION_FAILED")
    return flow_event(
        stage,
        record,
        run_id=canonical_run_id,
        task_id=str(task_id or ""),
        level="INFO" if success else "ERROR",
    )


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




def _markdown_inline(value: Any, *, limit: int = 600) -> str:
    raw = "" if value is None else str(value)
    text = _redact_text(raw).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "\\|").replace("`", "'")
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "-"


def _markdown_json(value: Any) -> list[str]:
    return ["```json", safe_json_dumps(value), "```"]


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def finalize_flow_markdown(
    *,
    run_id: str,
    question: str,
    execution: dict[str, Any] | None,
    runtime_status: str,
    success: bool,
    final_answer: str = "",
    user_id: str = "",
    session_id: str = "",
    language: str = "",
    llm_runtime: dict[str, Any] | None = None,
) -> str:
    """Append one complete, human-readable run archive to the flow Markdown.

    Major trace events remain useful while the request is running. This final
    snapshot guarantees that the saved Markdown still contains the Worker DAG,
    every public WorkerResult, execution batches, evidence references, missing
    context, errors and the final answer even when dense console tracing is off.
    It never mutates the Worker DAG and never exposes private Tool arguments.
    """
    if not flow_trace_enabled():
        return ""

    canonical_run_id = str(run_id or "").strip() or _CURRENT_RUN_ID.get()
    if not canonical_run_id:
        canonical_run_id = _new_fallback_run_id()
    payload = dict(execution or {})

    try:
        with _LOCK:
            path = _path_for_run(
                canonical_run_id,
                start_new=False,
                payload={"query": question},
            )
            marker = f"<!-- AGENT_RUN_FINAL_SNAPSHOT:{canonical_run_id} -->"
            if canonical_run_id in _RUN_FINALIZED:
                return str(path)
            try:
                if marker in path.read_text(encoding="utf-8"):
                    _RUN_FINALIZED.add(canonical_run_id)
                    return str(path)
            except OSError:
                pass

            graph_runtime = _as_mapping(payload.get("graph_runtime"))
            worker_dag = _as_mapping(graph_runtime.get("worker_dag"))
            planned_tasks = _as_rows(worker_dag.get("tasks"))
            task_results = _as_mapping(payload.get("task_results"))
            graph_results = _as_mapping(payload.get("graph_worker_results"))
            result_items = _as_rows(graph_results.get("items"))
            if not result_items:
                result_items = [
                    dict(item)
                    for item in task_results.values()
                    if isinstance(item, dict)
                ]
            result_by_task = {
                str(item.get("task_id") or ""): item
                for item in result_items
                if str(item.get("task_id") or "")
            }
            batches = _as_rows(payload.get("execution_batches"))
            timeline = _as_rows(payload.get("agent_timeline"))
            planner = _as_mapping(graph_runtime.get("planner"))
            warnings = [str(item) for item in payload.get("warnings") or []]
            errors = [str(item) for item in payload.get("errors") or []]
            missing_context = _as_rows(payload.get("missing_context"))
            failure = _as_mapping(payload.get("failure"))
            execution_status = str(payload.get("execution_status") or runtime_status or "unknown")
            tool_executions = _as_rows(payload.get("tool_executions"))
            if not tool_executions:
                tool_executions = [
                    dict(item)
                    for item in _RUN_TOOL_EXECUTIONS.get(canonical_run_id, [])
                    if isinstance(item, dict)
                ]

            lines: list[str] = [
                marker,
                "",
                "# 运行总览",
                "",
                "| 字段 | 内容 |",
                "|---|---|",
                f"| Run ID | `{_markdown_inline(canonical_run_id)}` |",
                f"| 用户问题 | {_markdown_inline(question, limit=1200)} |",
                f"| 用户 | `{_markdown_inline(user_id)}` |",
                f"| 会话 | `{_markdown_inline(session_id)}` |",
                f"| 回复语言 | `{_markdown_inline(language)}` |",
                f"| Runtime 状态 | `{_markdown_inline(runtime_status)}` |",
                f"| 执行状态 | `{_markdown_inline(execution_status)}` |",
                f"| 是否成功 | `{'true' if success else 'false'}` |",
                f"| Worker 计划数 | `{len(planned_tasks)}` |",
                f"| Worker 结果数 | `{len(result_items)}` |",
                f"| 完成数 | `{graph_results.get('completed_count', 0)}` |",
                f"| 失败数 | `{graph_results.get('failed_count', 0)}` |",
                f"| 等待上下文数 | `{graph_results.get('waiting_context_count', 0)}` |",
                f"| 内部运行计数 | `{payload.get('internal_tool_call_count', 0)}` |",
                f"| 已记录 Tool 调用数 | `{len(tool_executions)}` |",
                f"| 完成时间 | `{datetime.now().isoformat(timespec='milliseconds')}` |",
                "",
            ]

            if llm_runtime:
                lines.extend([
                    "## LLM 运行配置（已脱敏）",
                    "",
                    *_markdown_json(llm_runtime),
                    "",
                ])

            lines.extend([
                "## MainAgent 规划信息",
                "",
                *_markdown_json(planner),
                "",
            ])
            if failure:
                lines.extend([
                    "## 失败阶段与错误分类",
                    "",
                    *_markdown_json(failure),
                    "",
                ])
            lines.extend([
                "## Worker DAG",
                "",
            ])

            if planned_tasks:
                lines.extend([
                    "| 顺序 | Task ID | Worker ID | Worker 角色 | Task Type | 目标 | 依赖 | 预期输出 | 结果状态 |",
                    "|---:|---|---|---|---|---|---|---|---|",
                ])
                for index, task in enumerate(planned_tasks, start=1):
                    task_id = str(task.get("task_id") or "")
                    result = result_by_task.get(task_id, {})
                    dependencies = ", ".join(
                        str(item) for item in task.get("dependency_task_ids") or []
                    ) or "-"
                    lines.append(
                        "| {index} | `{task_id}` | `{worker_id}` | `{agent}` | `{task_type}` | {objective} | {deps} | `{output}` | `{status}` |".format(
                            index=index,
                            task_id=_markdown_inline(task_id),
                            worker_id=_markdown_inline(task.get("worker_id")),
                            agent=_markdown_inline(task.get("assigned_agent")),
                            task_type=_markdown_inline(task.get("task_type")),
                            objective=_markdown_inline(task.get("objective"), limit=900),
                            deps=_markdown_inline(dependencies),
                            output=_markdown_inline(task.get("expected_output_type")),
                            status=_markdown_inline(result.get("status") or task.get("status")),
                        )
                    )
                lines.append("")
                for task in planned_tasks:
                    task_id = str(task.get("task_id") or "")
                    lines.extend([
                        f"### 任务 `{_markdown_inline(task_id)}` 的结构化输入",
                        "",
                        "- Worker：`{}` / `{}`".format(
                            _markdown_inline(task.get("worker_id")),
                            _markdown_inline(task.get("assigned_agent")),
                        ),
                        "- 任务类型：`{}`".format(_markdown_inline(task.get("task_type"))),
                        "- 预期输出：`{}`".format(_markdown_inline(task.get("expected_output_type"))),
                        "- 约束：{}".format(_markdown_inline(", ".join(map(str, task.get("constraints") or [])) or "-")),
                        "",
                        *_markdown_json(task.get("args") or {}),
                        "",
                    ])
            else:
                lines.extend(["未保存到可公开的 Worker DAG 快照。", ""])

            lines.extend(["## 执行批次", ""])
            if batches:
                lines.extend([
                    "| 批次 | Task IDs | Worker 角色 | 是否并行 |",
                    "|---:|---|---|---|",
                ])
                for batch in batches:
                    lines.append(
                        "| `{}` | {} | {} | `{}` |".format(
                            _markdown_inline(batch.get("batch_index")),
                            _markdown_inline(", ".join(map(str, batch.get("task_ids") or []))),
                            _markdown_inline(", ".join(map(str, batch.get("agents") or []))),
                            _markdown_inline(batch.get("parallel")),
                        )
                    )
                lines.append("")
            else:
                lines.extend(["没有可用的执行批次记录。", ""])

            lines.extend(["## 工具执行状态", ""])
            if tool_executions:
                lines.extend([
                    "| Tool Call ID | Task ID | Tool | 状态 | 成功 | 耗时(ms) | 重试 | 错误类型 |",
                    "|---|---|---|---|---|---:|---:|---|",
                ])
                for item in tool_executions:
                    lines.append(
                        "| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                            _markdown_inline(item.get("tool_call_id")),
                            _markdown_inline(item.get("task_id")),
                            _markdown_inline(item.get("tool_name")),
                            _markdown_inline(item.get("status")),
                            _markdown_inline(item.get("success")),
                            _markdown_inline(item.get("duration_ms")),
                            _markdown_inline(item.get("retry_count")),
                            _markdown_inline(item.get("error_type")),
                        )
                    )
                lines.extend(["", "### Tool 执行详情（已脱敏）", "", *_markdown_json(tool_executions), ""])
            else:
                lines.extend(["本次运行没有记录到 Tool 调用，或调用发生在未携带 run_id 的独立工具上下文中。", ""])

            lines.extend(["## Worker 执行结果", ""])
            if result_items:
                lines.extend([
                    "| Task ID | Worker | 状态 | 输出类型 | 耗时(ms) | 置信度 | 证据 | 产物 | 摘要 |",
                    "|---|---|---|---|---:|---:|---:|---:|---|",
                ])
                for item in result_items:
                    metadata = _as_mapping(item.get("metadata"))
                    lines.append(
                        "| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | {} |".format(
                            _markdown_inline(item.get("task_id")),
                            _markdown_inline(item.get("agent_id")),
                            _markdown_inline(item.get("status")),
                            _markdown_inline(item.get("output_type")),
                            _markdown_inline(metadata.get("duration_ms")),
                            _markdown_inline(item.get("confidence")),
                            len(item.get("evidence_refs") or []),
                            len(item.get("artifact_refs") or []),
                            _markdown_inline(item.get("summary"), limit=700),
                        )
                    )
                lines.append("")

                for item in result_items:
                    task_id = str(item.get("task_id") or "unknown")
                    metadata = _as_mapping(item.get("metadata"))
                    lines.extend([
                        f"### WorkerResult `{_markdown_inline(task_id)}`",
                        "",
                        "- Worker：`{}`".format(_markdown_inline(item.get("agent_id"))),
                        "- 状态：`{}`".format(_markdown_inline(item.get("status"))),
                        "- 输出类型：`{}`".format(_markdown_inline(item.get("output_type"))),
                        "- 耗时：`{} ms`".format(_markdown_inline(metadata.get("duration_ms"))),
                        "- 摘要：{}".format(_markdown_inline(item.get("summary"), limit=1800)),
                        "",
                    ])
                    tool_execution = _as_mapping(metadata.get("tool_execution"))
                    if tool_execution:
                        lines.extend([
                            "#### 私有 Tool 执行摘要",
                            "",
                            *_markdown_json(tool_execution),
                            "",
                        ])
                    if item.get("error"):
                        lines.extend(["#### 错误", "", *_markdown_json(item.get("error")), ""])
                    if item.get("missing_items"):
                        lines.extend(["#### 缺少上下文", "", *_markdown_json(item.get("missing_items")), ""])
                    if item.get("warnings"):
                        lines.extend(["#### 警告", "", *_markdown_json(item.get("warnings")), ""])
                    if item.get("findings"):
                        lines.extend(["#### 关键发现", "", *_markdown_json(item.get("findings")), ""])
                    if item.get("recommendations"):
                        lines.extend(["#### 建议", "", *_markdown_json(item.get("recommendations")), ""])
                    if item.get("evidence_refs"):
                        lines.extend(["#### 证据引用", "", *_markdown_json(item.get("evidence_refs")), ""])
                    if item.get("graph_path_refs"):
                        lines.extend(["#### 图关系路径", "", *_markdown_json(item.get("graph_path_refs")), ""])
                    if item.get("artifact_refs"):
                        lines.extend(["#### 产物引用", "", *_markdown_json(item.get("artifact_refs")), ""])
                    if item.get("data") is not None:
                        lines.extend(["#### 结构化业务输出", "", *_markdown_json(item.get("data")), ""])
            else:
                lines.extend(["没有 WorkerResult。", ""])

            if timeline:
                lines.extend(["## Worker 时间线", "", *_markdown_json(timeline), ""])

            focus_refs = graph_runtime.get("focus_refs") or []
            if focus_refs:
                lines.extend(["## 已解析 GraphRef", "", *_markdown_json(focus_refs), ""])
            resolution_audit = graph_runtime.get("resolution_audit")
            if resolution_audit:
                lines.extend(["## GraphRef 解析审计", "", *_markdown_json(resolution_audit), ""])

            if missing_context:
                lines.extend(["## 等待用户补充的信息", "", *_markdown_json(missing_context), ""])

            lines.extend(["## 最终回答", ""])
            if final_answer:
                lines.extend([_redact_text(str(final_answer)), ""])
            else:
                lines.extend(["未生成最终回答。", ""])

            if warnings:
                lines.extend(["## 全局警告", "", *_markdown_json(warnings), ""])
            if errors:
                lines.extend(["## 全局错误", "", *_markdown_json(errors), ""])

            lines.extend([
                "## 运行边界说明",
                "",
                "- 本文档保存的是 MainAgent 可见的 Worker DAG、公开 WorkerResult 和安全化运行信息。",
                "- Worker 私有 Tool 的原始参数、原始响应、密钥、数据库路径和内部推理不会写入本文档。",
                "- Tool 的逐次执行状态、耗时、错误分类、重试次数和产物引用会保存；原始参数值、原始响应、密钥、数据库路径和内部 traceback 不会写入本文档。",
                "",
                "---",
                "",
            ])

            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines))

            _RUN_FINALIZED.add(canonical_run_id)
            _RUN_TOOL_EXECUTIONS.pop(canonical_run_id, None)
            return str(path)
    except Exception:
        return ""


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

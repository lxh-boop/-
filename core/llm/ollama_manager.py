"""Safe, bounded management helpers for the project Ollama profile."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


OLLAMA_BASE_URL = "http://127.0.0.1:11434"
RECOMMENDED_BASE_MODEL = "qwen3:4b"
PROJECT_MODEL = "stock-agent-qwen3-4b"
PROJECT_MODELFILE_NAME = "Modelfile.stock-agent-qwen3-4b"
_MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$", re.IGNORECASE)


@dataclass(frozen=True)
class OllamaResult:
    success: bool
    message: str
    data: dict[str, Any]


def _result(success: bool, message: str, **data: Any) -> OllamaResult:
    return OllamaResult(success=success, message=message, data=data)


def _valid_model_name(model: str) -> bool:
    return bool(_MODEL_PATTERN.fullmatch(str(model or "")))


def is_valid_model_name(model: str) -> bool:
    """Public validation boundary for selectable installed model names."""
    return _valid_model_name(model)


def _same_ollama_model(left: str, right: str) -> bool:
    """Treat an omitted Ollama tag as the default ``:latest`` tag."""
    left_text = str(left or "").strip().lower()
    right_text = str(right or "").strip().lower()
    return left_text == right_text or {left_text, right_text} == {
        left_text.split(":", 1)[0],
        f"{left_text.split(':', 1)[0]}:latest",
    }


def is_ollama_installed() -> bool:
    return _ollama_executable() is not None


def _ollama_executable() -> str | None:
    """Find the official Windows installation even before PATH is refreshed."""
    discovered = shutil.which("ollama")
    if discovered:
        return discovered
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def get_ollama_version(timeout_seconds: int = 10) -> OllamaResult:
    if not is_ollama_installed():
        return _result(False, "Ollama 未安装。请从 https://ollama.com/download/windows 安装后重试。")
    try:
        completed = subprocess.run([str(_ollama_executable()), "--version"], capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result(False, f"无法执行 Ollama：{type(exc).__name__}")
    text = (completed.stdout or completed.stderr or "").strip()
    return _result(completed.returncode == 0, text or "无法读取 Ollama 版本", returncode=completed.returncode)


def _request_json(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout_seconds: int = 10) -> tuple[bool, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(f"{OLLAMA_BASE_URL}{path}", data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: fixed loopback endpoint
            return True, json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def is_ollama_running(timeout_seconds: int = 5) -> bool:
    ok, _ = _request_json("/api/tags", timeout_seconds=timeout_seconds)
    return ok


def list_local_models(timeout_seconds: int = 10) -> OllamaResult:
    if not is_ollama_installed():
        return _result(False, "Ollama 未安装。请先从 https://ollama.com/download/windows 安装后重试。", models=[])
    ok, payload = _request_json("/api/tags", timeout_seconds=timeout_seconds)
    if not ok:
        return _result(False, "Ollama 服务不可访问。请启动 Ollama 后重试。", models=[], error=str(payload)[:300])
    models = sorted({str(item.get("name") or "") for item in (payload.get("models") or []) if isinstance(item, dict) and item.get("name")})
    return _result(True, "Ollama 服务正常。", models=models)


def _run_ollama(args: list[str], *, timeout_seconds: int = 1800) -> OllamaResult:
    if not is_ollama_installed():
        return _result(False, "Ollama 未安装。请从 https://ollama.com/download/windows 安装后重试。")
    try:
        completed = subprocess.run([str(_ollama_executable()), *args], capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return _result(False, "Ollama 操作超时。", command=args)
    except OSError as exc:
        return _result(False, f"无法执行 Ollama：{type(exc).__name__}", command=args)
    message = (completed.stdout or completed.stderr or "").strip()
    return _result(completed.returncode == 0, message or "Ollama 未返回输出", command=args, returncode=completed.returncode)


def pull_model(model: str = RECOMMENDED_BASE_MODEL, *, timeout_seconds: int = 1800) -> OllamaResult:
    if model != RECOMMENDED_BASE_MODEL or not _valid_model_name(model):
        return _result(False, "仅允许下载项目推荐基础模型 qwen3:4b。")
    return _run_ollama(["pull", model], timeout_seconds=timeout_seconds)


def create_project_model(modelfile: str | Path, *, timeout_seconds: int = 300) -> OllamaResult:
    path = Path(modelfile).resolve()
    if not path.exists() or path.name != PROJECT_MODELFILE_NAME:
        return _result(False, "项目 Modelfile 不存在或名称不正确。")
    return _run_ollama(["create", PROJECT_MODEL, "-f", str(path)], timeout_seconds=timeout_seconds)


def validate_local_model(model: str = PROJECT_MODEL, *, timeout_seconds: int = 120) -> OllamaResult:
    if not _valid_model_name(model):
        return _result(False, "本地模型名称不合法。")
    listed = list_local_models(timeout_seconds=timeout_seconds)
    if not listed.success:
        return listed
    available_models = set(listed.data.get("models") or [])
    if not any(_same_ollama_model(model, candidate) for candidate in available_models):
        return _result(False, f"未找到本地模型 {model}。请先下载 qwen3:4b 并创建项目模型。", models=listed.data.get("models") or [])
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只回复 OK。"},
            {"role": "user", "content": "只回复 OK"},
        ],
        "temperature": 0,
        "max_tokens": 200,
    }
    ok, response = _request_json("/v1/chat/completions", method="POST", payload=payload, timeout_seconds=timeout_seconds)
    if not ok:
        return _result(False, "本地 Ollama chat/completions 验证失败。", error=str(response)[:300])
    try:
        content = str(response["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        content = ""
    if not content:
        return _result(False, "本地 Ollama 返回为空内容。")
    return _result(True, f"本地 Ollama 连接成功，当前模型：{model}", content=content[:100])

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from server.task_runtime.store import ACTIVE_STATUSES, TERMINAL_STATUSES, TaskStore, utc_now

ALLOWED_TASK_TYPES = {
    "diagnostic.sleep",
    "diagnostic.flaky",
    "agent.run",
    "dashboard.rolling_update",
    "dashboard.backtest",
    "paper-trading.update",
    "paper-profile.ai-news-adjustment",
    "paper-profile.scheduler-manual",
}


class TaskManager:
    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path or os.environ.get("STOCK_AGENT_TASK_DB") or "runtime/task_runtime.sqlite3")
        if not path.is_absolute():
            path = Path.cwd() / path
        self.store = TaskStore(path)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self.store.recover_interrupted()

    @property
    def db_path(self) -> Path:
        return self.store.db_path

    def submit(
        self,
        *,
        task_type: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        owner_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        timeout_seconds: int = 600,
        max_retries: int = 0,
        secrets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        task_type = str(task_type)
        if task_type not in ALLOWED_TASK_TYPES:
            raise KeyError(f"Task type is not allowed: {task_type}")
        max_concurrent = max(1, int(os.environ.get("STOCK_AGENT_MAX_CONCURRENT_TASKS") or 4))
        with self._lock:
            active_count = len(self.store.list(active_only=True, limit=200))
            if active_count >= max_concurrent:
                raise RuntimeError(
                    f"Task concurrency limit reached: {active_count}/{max_concurrent}"
                )
        task_id = f"task_{uuid.uuid4().hex}"
        self.store.create(
            task_id=task_id,
            task_type=task_type,
            request={"args": list(args or []), "kwargs": dict(kwargs or {})},
            owner_id=str(owner_id or ""),
            session_id=str(session_id or ""),
            metadata=dict(metadata or {}),
            timeout_seconds=max(1, int(timeout_seconds)),
            max_retries=max(0, int(max_retries)),
        )
        env = os.environ.copy()
        if secrets:
            env["STOCK_TASK_SECRET_B64"] = base64.b64encode(
                json.dumps(secrets, ensure_ascii=False).encode("utf-8")
            ).decode("ascii")
        command = [
            sys.executable,
            "-m",
            "server.task_runtime.worker",
            "--task-id",
            task_id,
            "--db-path",
            str(self.db_path),
            "--parent-pid",
            str(os.getpid()),
        ]
        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            start_new_session = True
        process = subprocess.Popen(
            command,
            cwd=str(Path.cwd()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        self.store.update(task_id, worker_pid=int(process.pid))
        with self._lock:
            self._processes[task_id] = process
        threading.Thread(
            target=self._monitor,
            args=(task_id, process),
            name=f"task-monitor-{task_id[-8:]}",
            daemon=True,
        ).start()
        return self.store.get(task_id)

    def _terminate_tree(self, process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _monitor(self, task_id: str, process: subprocess.Popen[Any]) -> None:
        started = time.monotonic()
        try:
            while process.poll() is None:
                task = self.store.get(task_id)
                if task.get("cancel_requested"):
                    self._terminate_tree(process)
                    current = self.store.get(task_id)
                    if current["status"] not in TERMINAL_STATUSES:
                        self.store.update(task_id, status="cancelled", finished_at=utc_now(), progress=1, message="任务已取消", worker_pid=None)
                        self.store.add_event(task_id, "cancelled", {"message": "任务进程已终止"})
                    return
                if time.monotonic() - started > int(task.get("timeout_seconds") or 600):
                    self._terminate_tree(process)
                    current = self.store.get(task_id)
                    if current["status"] not in TERMINAL_STATUSES:
                        self.store.update(task_id, status="timed_out", finished_at=utc_now(), progress=1, message="任务执行超时", worker_pid=None)
                        self.store.add_event(task_id, "timed_out", {"message": "任务超过服务端超时限制，进程已终止"})
                    return
                time.sleep(0.5)
            current = self.store.get(task_id)
            if current["status"] not in TERMINAL_STATUSES:
                code = int(process.returncode or 0)
                self.store.update(
                    task_id,
                    status="failed" if code else "interrupted",
                    finished_at=utc_now(),
                    progress=1,
                    message=f"任务 Worker 异常退出，返回码 {code}",
                    error={"code": "WORKER_EXIT", "message": f"Worker exited with code {code}"},
                    worker_pid=None,
                )
                self.store.add_event(task_id, "worker_exit", {"returncode": code})
        finally:
            with self._lock:
                self._processes.pop(task_id, None)

    def cancel(self, task_id: str) -> dict[str, Any]:
        return self.store.request_cancel(task_id)


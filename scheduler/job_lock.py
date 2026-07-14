from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_LOCK_PATH = Path("runtime") / "locks" / "daily_update.lock"


class JobLockError(RuntimeError):
    pass


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            synchronize = 0x00100000
            handle = open_process(synchronize, False, int(pid))
            if handle:
                close_handle(handle)
                return True
            error_code = ctypes.get_last_error()
            return error_code == 5
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


@dataclass
class JobLock:
    lock_path: Path = DEFAULT_LOCK_PATH
    job_id: str = ""
    trade_date: str = ""
    force: bool = False

    def read_lock(self) -> dict[str, Any] | None:
        if not self.lock_path.exists():
            return None
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {"pid": -1, "corrupt": True}

    def is_stale(self, data: dict[str, Any] | None = None) -> bool:
        payload = data if data is not None else self.read_lock()
        if not payload:
            return False
        return not process_exists(int(payload.get("pid") or -1))

    def acquire(self) -> dict[str, Any]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read_lock()
        if existing:
            if self.is_stale(existing):
                self.lock_path.unlink(missing_ok=True)
            elif not self.force:
                raise JobLockError(
                    f"daily update is already running: pid={existing.get('pid')} job_id={existing.get('job_id')}"
                )
            else:
                raise JobLockError(
                    "force cannot bypass a live daily update lock; wait for the running worker or remove a stale lock"
                )

        payload = {
            "job_id": self.job_id,
            "pid": os.getpid(),
            "trade_date": self.trade_date,
            "started_at": now_text(),
            "hostname": socket.gethostname(),
        }
        self.lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def release(self) -> None:
        current = self.read_lock()
        if current and int(current.get("pid") or -1) == os.getpid():
            self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> "JobLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False

from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.task_runtime.manager import TaskManager

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


def wait(manager: TaskManager, task_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = manager.store.get(task_id)
        if task["status"] in TERMINAL:
            return task
        time.sleep(0.1)
    raise TimeoutError(task_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True)
    args = parser.parse_args()
    db_path = Path(args.db_path)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()
    manager = TaskManager(db_path)
    success = manager.submit(task_type="diagnostic.sleep", kwargs={"seconds": 0.4, "steps": 2}, timeout_seconds=5)
    success_final = wait(manager, success["task_id"])
    cancelled = manager.submit(task_type="diagnostic.sleep", kwargs={"seconds": 5, "steps": 20}, timeout_seconds=10)
    time.sleep(0.5)
    manager.cancel(cancelled["task_id"])
    cancel_final = wait(manager, cancelled["task_id"])
    payload = {
        "success_status": success_final["status"],
        "cancel_status": cancel_final["status"],
        "passed": success_final["status"] == "succeeded" and cancel_final["status"] == "cancelled",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

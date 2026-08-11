from __future__ import annotations

from pathlib import Path

from server.task_runtime.manager import TaskManager
from server.task_runtime.store import TaskStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _seed_running_task(db_path: Path) -> TaskStore:
    store = TaskStore(db_path)
    store.create(
        task_id="task_live",
        task_type="agent.run",
        request={"args": [], "kwargs": {}},
    )
    store.update("task_live", status="running", worker_pid=12345)
    return store


def test_constructing_second_manager_does_not_interrupt_live_task(tmp_path: Path) -> None:
    db_path = tmp_path / "task_runtime.sqlite3"
    store = _seed_running_task(db_path)

    TaskManager(db_path)

    assert store.get("task_live")["status"] == "running"


def test_explicit_api_startup_recovery_is_one_shot(tmp_path: Path) -> None:
    db_path = tmp_path / "task_runtime.sqlite3"
    store = _seed_running_task(db_path)
    manager = TaskManager(db_path)

    assert manager.recover_on_api_startup() == ["task_live"]
    assert store.get("task_live")["status"] == "interrupted"
    assert manager.recover_on_api_startup() == []


def test_compose_places_task_sqlite_on_named_linux_volume() -> None:
    text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'STOCK_AGENT_TASK_DB: /app/runtime/task_runtime.sqlite3' in text
    assert 'STOCK_AGENT_RECOVER_INTERRUPTED_ON_START: "1"' in text
    assert "source: task_runtime_data\n        target: /app/runtime" in text
    assert "name: stock_daily_app_task_runtime" in text


def test_frontend_finalization_has_bounded_retry() -> None:
    text = (PROJECT_ROOT / "frontend/src/pages/agent/AgentPage.tsx").read_text(encoding="utf-8")

    assert "FINALIZE_RETRY_DELAYS_MS = [0, 1500, 4000, 8000]" in text
    assert "for (const delayMs of FINALIZE_RETRY_DELAYS_MS)" in text
    assert "await agentApi.finalizeTask" in text
    assert "已自动重试" in text

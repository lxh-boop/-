from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8")


def parse(relative: str) -> ast.AST:
    return ast.parse(read(relative), filename=relative)


def assert_contains(relative: str, *values: str) -> None:
    text = read(relative)
    for value in values:
        if value not in text:
            raise AssertionError(f"{relative} missing architecture marker: {value}")


def main() -> int:
    for relative in (
        "agent/executor.py",
        "agent/runtime.py",
        "agent/collaboration/integration.py",
        "agent/collaboration/coordinator.py",
        "agent/collaboration/runtime_services.py",
    ):
        parse(relative)

    assert_contains(
        "agent/executor.py",
        "runtime_recorder=runtime",
    )
    assert_contains(
        "agent/collaboration/integration.py",
        "runtime_recorder: AgentRuntimeRecorder | None = None",
        "CollaborationRuntimeServices.from_recorder",
        "runtime_services=runtime_services",
    )
    assert_contains(
        "agent/collaboration/coordinator.py",
        "self.runtime_services.register_tasks(tasks)",
        "self.runtime_services.mark_ready(task)",
        "self.runtime_services.mark_running(task)",
        "self.runtime_services.record_result(task, result)",
    )
    assert_contains(
        "agent/runtime.py",
        "def transition_step(",
        "illegal_step_transition",
    )
    assert_contains(
        "agent/collaboration/runtime_services.py",
        '"runtime_layer": "worker_dag"',
        "worker_result_status",
        "collaboration_runtime_identity_mismatch",
    )

    forbidden_new_paths = (
        "agent/supervisor.py",
        "agent/agent_events.py",
        "agent/agent_artifacts.py",
        "agent/collaboration_v3",
    )
    for relative in forbidden_new_paths:
        if (ROOT / relative).exists():
            raise AssertionError(f"forbidden duplicate runtime path exists: {relative}")

    print("[OK] Supervisor-Worker phase 1 architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

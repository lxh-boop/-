"""Read-only application operations for system and user context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.sandbox import run_python_analysis
from portfolio.user_profile import load_user_context
from scheduler.job_state import load_latest_job_status


def list_latest_reports(
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    """Return the latest generated report files without Agent semantics."""

    root = Path(output_dir)
    candidates: list[Path] = []
    for pattern in (
        "reports/**/*",
        "*report*",
        "portfolio/*/history/risk/*.json",
    ):
        candidates.extend(
            path for path in root.glob(pattern) if path.is_file()
        )
    latest = sorted(
        candidates,
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:10]
    return {
        "status": "success" if latest else "no_reports",
        "reports": [
            {
                "path": str(path),
                "name": path.name,
                "modified_time": path.stat().st_mtime,
            }
            for path in latest
        ],
    }


def read_scheduler_status(root: str | Path = ".") -> dict[str, Any]:
    """Read scheduler state and a bounded log tail."""

    status = load_latest_job_status(root)
    log_dir = Path(root) / "logs" / "scheduler"
    logs = sorted(log_dir.glob("*.log")) if log_dir.exists() else []
    tail = ""
    if logs:
        try:
            lines = logs[-1].read_text(
                encoding="utf-8",
                errors="ignore",
            ).splitlines()
            tail = "\n".join(lines[-20:])
        except Exception:
            tail = ""
    return {
        "status": "success" if status else "missing_status",
        "latest_job_status": status,
        "latest_log_path": str(logs[-1]) if logs else "",
        "latest_log_tail": tail,
    }


def read_user_profile(
    user_id: str,
    *,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    """Load the user's profile, risk assessment, goal, and constraints."""

    profile, risk, goal, constraints = load_user_context(
        user_id,
        db_path=db_path,
        output_dir=output_dir,
    )
    return {
        "user_id": str(user_id or "default"),
        "profile": profile.to_dict(),
        "risk_assessment": risk.to_dict(),
        "investment_goal": goal.to_dict(),
        "constraints": dict(constraints),
        "trading_permissions": dict(
            constraints.get("trading_permissions") or {}
        ),
        "status": "success",
    }


def run_readonly_python_analysis(
    code: str,
    *,
    snapshot: dict[str, Any] | None = None,
    snapshot_id: str = "",
    timeout_seconds: float = 5.0,
    max_output_chars: int = 4000,
) -> dict[str, Any]:
    """Run the restricted analysis sandbox and return a business result."""

    result = run_python_analysis(
        code,
        snapshot=snapshot or {},
        snapshot_id=snapshot_id,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
    return {
        "success": bool(result.get("success")),
        "message": str(result.get("status") or ""),
        "data": {
            **dict(result),
            "read_only": True,
            "mutation_performed": False,
            "business_state_write_allowed": False,
        },
        "warnings": list(result.get("warnings") or []),
        "errors": (
            [str(result.get("error_type"))]
            if result.get("error_type")
            else []
        ),
        "status": str(result.get("status") or ""),
    }


__all__ = [
    "list_latest_reports",
    "read_scheduler_status",
    "read_user_profile",
    "run_readonly_python_analysis",
]

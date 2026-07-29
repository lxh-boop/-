from __future__ import annotations

from typing import Any

from application.use_cases.system_queries import (
    run_readonly_python_analysis,
)


class PythonSandboxService:
    """Read-only service wrapper around the restricted analysis sandbox."""

    def run_analysis(
        self,
        code: str,
        *,
        snapshot: dict[str, Any] | None = None,
        snapshot_id: str = "",
        timeout_seconds: float = 995.0,
        max_output_chars: int = 4000,
    ) -> dict[str, Any]:
        return run_readonly_python_analysis(
            code,
            snapshot=snapshot or {},
            snapshot_id=snapshot_id,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        )


python_sandbox_service = PythonSandboxService()

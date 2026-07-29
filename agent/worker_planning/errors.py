"""Errors shared by Worker plan input binding and execution."""

from __future__ import annotations

from agent.collaboration.models import MissingContextItem


class WorkerContextRequired(RuntimeError):
    """Raised by a deterministic argument builder for missing business input."""

    def __init__(self, items: list[MissingContextItem]) -> None:
        self.items = list(items)
        super().__init__(
            "worker_context_required:"
            + ",".join(item.key for item in self.items)
        )


__all__ = ["WorkerContextRequired"]

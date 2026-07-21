"""Private process-only dependencies for tools that need the run's LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from weakref import WeakValueDictionary

from core.llm.service import LLMService


@dataclass(frozen=True)
class LLMExecutionDependencies:
    llm_service: LLMService = field(repr=False)

    @property
    def profile_id(self) -> str:
        return self.llm_service.profile_id

    @property
    def config_hash(self) -> str:
        return self.llm_service.config_hash


_RUN_DEPENDENCIES: WeakValueDictionary[str, LLMExecutionDependencies] = WeakValueDictionary()
_LOCK = RLock()


def register_llm_execution_dependencies(run_id: str, dependencies: LLMExecutionDependencies) -> None:
    key = str(run_id or "").strip()
    if not key:
        raise ValueError("run_id is required for runtime dependencies")
    with _LOCK:
        _RUN_DEPENDENCIES[key] = dependencies


def get_llm_execution_dependencies(run_id: str) -> LLMExecutionDependencies | None:
    with _LOCK:
        return _RUN_DEPENDENCIES.get(str(run_id or "").strip())


__all__ = [
    "LLMExecutionDependencies",
    "get_llm_execution_dependencies",
    "register_llm_execution_dependencies",
]

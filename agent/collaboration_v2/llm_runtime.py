from __future__ import annotations

from dataclasses import dataclass

from core.llm import LLMService
from core.llm.dependencies import get_llm_execution_dependencies


class CollaborationLLMUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RunLLMBinding:
    service: LLMService
    run_id: str
    profile_id: str
    config_hash: str
    source: str

    def public_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "config_hash": self.config_hash,
            "source": self.source,
        }


def require_run_llm_service(
    *,
    llm_service: LLMService | None,
    run_id: str,
) -> RunLLMBinding:
    """Resolve the one immutable LLMService already created by the Executor.

    This function never creates a model service and never resolves model settings.
    It may only recover the exact service registered for the current run.
    """

    key = str(run_id or "").strip()
    registered = get_llm_execution_dependencies(key) if key else None
    registered_service = registered.llm_service if registered is not None else None

    if llm_service is None:
        llm_service = registered_service
        source = "run_dependency_registry"
    else:
        source = "executor_argument"

    if llm_service is None:
        raise CollaborationLLMUnavailable("llm_service_unavailable_for_agent_run")

    if registered_service is not None and registered_service is not llm_service:
        raise CollaborationLLMUnavailable("llm_service_identity_mismatch_for_agent_run")

    if not llm_service.is_available:
        raise CollaborationLLMUnavailable("llm_service_not_configured")

    return RunLLMBinding(
        service=llm_service,
        run_id=key,
        profile_id=llm_service.profile_id,
        config_hash=llm_service.config_hash,
        source=source,
    )

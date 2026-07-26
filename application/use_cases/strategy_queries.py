"""Read-only strategy workflow queries without Agent tool contracts."""

from __future__ import annotations

from pathlib import Path

from agent.services.strategy_audit_service import StrategyAuditService
from agent.services.strategy_context_service import StrategyContextService
from agent.services.strategy_proposal_service import StrategyProposalService
from application.contracts import BusinessResult


def _scope(
    *,
    user_id: str,
    account_id: str,
    conversation_id: str,
) -> tuple[str, str, str]:
    scoped_user = str(user_id or "default")
    scoped_account = str(account_id or f"paper_{scoped_user}")
    return scoped_user, scoped_account, str(conversation_id or "")


def read_strategy_context(
    *,
    user_id: str,
    account_id: str = "",
    conversation_id: str = "",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> BusinessResult:
    """Load the scoped long-term strategy conversation context."""

    scoped_user, scoped_account, scoped_conversation = _scope(
        user_id=user_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    context = StrategyContextService(
        db_path=db_path,
        output_dir=output_dir,
    ).load(
        user_id=scoped_user,
        account_id=scoped_account,
        conversation_id=scoped_conversation,
    )
    return BusinessResult(
        success=True,
        message="Strategy conversation context loaded.",
        data={"strategy_conversation_context": context.to_dict()},
    )


def read_active_strategy_proposal(
    *,
    user_id: str,
    account_id: str = "",
    conversation_id: str = "",
    db_path: str | Path | None = None,
) -> BusinessResult:
    """Load the active versioned proposal for one exact conversation scope."""

    scoped_user, scoped_account, scoped_conversation = _scope(
        user_id=user_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    service = StrategyProposalService(db_path)
    proposal = service.get_active(
        user_id=scoped_user,
        account_id=scoped_account,
        conversation_id=scoped_conversation,
    )
    versions = (
        service.list_versions(proposal.proposal_id, user_id=scoped_user)
        if proposal
        else []
    )
    return BusinessResult(
        success=True,
        message="Active strategy proposal loaded.",
        data={
            "proposal": proposal.to_dict() if proposal else {},
            "versions": [item.to_dict() for item in versions],
        },
    )


def read_strategy_audit_trace(
    *,
    user_id: str,
    proposal_id: str = "",
    implementation_id: str = "",
    plan_id: str = "",
    commit_id: str = "",
    binding_id: str = "",
    run_id: str = "",
    conversation_id: str = "",
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
) -> BusinessResult:
    """Reconstruct the redacted strategy lifecycle audit trace."""

    trace = StrategyAuditService(
        db_path=db_path,
        output_dir=output_dir,
    ).trace(
        user_id=user_id,
        proposal_id=proposal_id,
        implementation_id=implementation_id,
        plan_id=plan_id,
        commit_id=commit_id,
        binding_id=binding_id,
        run_id=run_id,
        conversation_id=conversation_id,
    )
    return BusinessResult(
        success=True,
        message="Strategy lifecycle audit trace loaded.",
        data={"strategy_audit_trace": trace},
    )


__all__ = [
    "read_active_strategy_proposal",
    "read_strategy_audit_trace",
    "read_strategy_context",
]

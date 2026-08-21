from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from agent.collaboration.write_runtime import WriteRequestExecutor
from agent.proposals import ProposalStatus, ProposalStore, ProposalStoreError
from agent.session.pending_action_store import save_pending_plan
from application.web_agent_service import WebAgentApplicationService


def _payload() -> dict[str, object]:
    return {
        "proposal_type": "portfolio_mutation",
        "operation_type": "adjust_position",
        "target": {"stock_code": "600000"},
        "changes": {"requested_weight": 0.05},
        "execution_parameters": {"stock_code": "600000", "requested_weight": 0.05},
        "rationale": "test",
    }


def _proposal(store: ProposalStore, *, session_id: str = "conv_1", expires_at: str = ""):
    return store.create(
        proposal_type="portfolio_mutation",
        user_id="u1",
        session_id=session_id,
        source_run_id="run_1",
        source_request_id="request_1",
        payload=_payload(),
        expires_at=expires_at,
    )


def test_proposal_store_uses_formal_migrations_and_forbids_terminal_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite3"
    store = ProposalStore(output_dir=tmp_path / "outputs", db_path=db_path)
    proposal = _proposal(store)

    assert store.path == db_path
    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {"proposals", "proposal_versions", "proposal_action_requests"} <= tables

    rejected = store.transition(
        proposal_id=proposal.proposal_id,
        user_id="u1",
        target=ProposalStatus.REJECTED,
    )
    assert rejected.status is ProposalStatus.REJECTED
    with pytest.raises(ProposalStoreError, match="proposal_revision_forbidden:rejected"):
        store.revise(
            proposal_id=proposal.proposal_id,
            user_id="u1",
            payload={**_payload(), "rationale": "must not revive"},
        )


def test_expired_proposal_is_not_approvable(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite3"
    store = ProposalStore(db_path=db_path)
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    proposal = _proposal(store, expires_at=expired_at)

    loaded = store.get(proposal.proposal_id)
    assert loaded is not None
    assert loaded.status is ProposalStatus.EXPIRED
    with pytest.raises(ProposalStoreError, match="proposal_not_pending:expired"):
        store.claim_for_execution(
            proposal_id=proposal.proposal_id,
            user_id="u1",
            expected_version=proposal.current_version,
            expected_payload_hash=proposal.current_payload_hash,
            approved_by="u1",
            approval_run_id="approval_run",
        )


def test_write_runtime_is_scoped_atomic_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite3"
    output_dir = tmp_path / "outputs"
    store = ProposalStore(db_path=db_path)
    proposal = _proposal(store)
    calls: list[str] = []

    class Capability:
        def execute(self, **kwargs):
            calls.append(kwargs["proposal"].proposal_id)
            return {
                "success": True,
                "code": "fake_commit",
                "business_effect_applied": True,
            }

    runtime = WriteRequestExecutor(output_dir=output_dir, db_path=db_path)
    runtime.capabilities = Capability()

    wrong_session = runtime.execute(
        action_type="confirm_execute",
        query="",
        user_id="u1",
        session_id="conv_wrong",
        run_id="approval_1",
        context={"proposal_id": proposal.proposal_id},
        idempotency_key="idem_wrong",
    )
    assert wrong_session["success"] is False
    assert wrong_session["outcome"] == "proposal_scope_mismatch"
    assert calls == []

    first = runtime.execute(
        action_type="confirm_execute",
        query="",
        user_id="u1",
        session_id="conv_1",
        run_id="approval_1",
        context={"proposal_id": proposal.proposal_id},
        idempotency_key="idem_confirm",
    )
    second = runtime.execute(
        action_type="confirm_execute",
        query="",
        user_id="u1",
        session_id="conv_1",
        run_id="approval_1",
        context={"proposal_id": proposal.proposal_id},
        idempotency_key="idem_confirm",
    )
    assert first["success"] is True
    assert first["proposal_status"] == "executed"
    assert second["success"] is True
    assert second["idempotent_replay"] is True
    assert calls == [proposal.proposal_id]


def test_agent_web_lists_only_canonical_proposals_not_legacy_pending_plans(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite3"
    output_dir = tmp_path / "outputs"
    service = WebAgentApplicationService(output_dir=output_dir, db_path=db_path)
    conversation_id = service.create_session(user_id="u1")["conversation_id"]
    proposal = _proposal(ProposalStore(db_path=db_path), session_id=conversation_id)
    save_pending_plan(
        "u1",
        {
            "plan_id": "plan_legacy_must_not_be_listed",
            "intent": "execute_add_stock",
            "execution_status": "pending",
        },
        output_dir,
    )

    page = service.pending_actions("u1", conversation_id=conversation_id)
    assert page["total"] == 1
    assert page["records"][0]["proposal_id"] == proposal.proposal_id
    assert page["records"][0]["plan_id"] == proposal.proposal_id
    assert "plan_legacy_must_not_be_listed" not in str(page)


def test_agent_web_control_maps_frozen_route_to_canonical_runtime_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "agent.sqlite3"
    service = WebAgentApplicationService(output_dir=tmp_path / "outputs", db_path=db_path)
    conversation_id = service.create_session(user_id="u1")["conversation_id"]
    proposal = _proposal(ProposalStore(db_path=db_path), session_id=conversation_id)
    captured: dict[str, object] = {}

    def control_action(_self, **kwargs):
        captured.update(kwargs)
        return {"success": True, "proposal_id": kwargs["proposal_id"]}

    monkeypatch.setattr(type(service.agent), "control_action", control_action)
    response = service.control_pending_action(
        action="confirm",
        user_id="u1",
        conversation_id=conversation_id,
        plan_id=proposal.proposal_id,
        confirmation_text=service._confirmation_phrase(proposal.proposal_id),
        request_id="request_web_1",
        idempotency_key="idem_web_1",
    )

    assert response["result"]["success"] is True
    assert captured["proposal_id"] == proposal.proposal_id
    assert captured["idempotency_key"] == "idem_web_1"
    assert "plan_id" not in captured
    assert "confirmation_token" not in captured

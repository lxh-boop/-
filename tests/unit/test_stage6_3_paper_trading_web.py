from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from application.web_paper_trading_service import WebPaperTradingApplicationService
from server.api.main import create_app
from server.api.presenters.paper_trading import present_write_result
from server.api.schemas.paper_trading import ProfileUpdateRequest, ProposalCommitRequest

ROOT = Path(__file__).resolve().parents[2]


def test_stage6_3_paper_routes_and_methods() -> None:
    paths = create_app().openapi()["paths"]
    prefix = "/api/v1/web/paper-trading"
    expected = {
        f"{prefix}/summary": {"get"},
        f"{prefix}/account": {"get"},
        f"{prefix}/positions": {"get"},
        f"{prefix}/orders": {"get"},
        f"{prefix}/profile": {"get", "put"},
        f"{prefix}/cash-flows": {"get"},
        f"{prefix}/cash-flows/preview": {"post"},
        f"{prefix}/cash-flows/{{cash_flow_id}}/cancel": {"post"},
        f"{prefix}/backfill/preview": {"post"},
        f"{prefix}/proposals": {"get"},
        f"{prefix}/proposals/{{plan_id}}": {"get"},
        f"{prefix}/proposals/{{plan_id}}/commit": {"post"},
        f"{prefix}/proposals/{{plan_id}}/reject": {"post"},
    }
    assert expected.keys() <= paths.keys()
    for path, methods in expected.items():
        assert methods <= set(paths[path])


def test_write_request_requires_idempotency_metadata() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(user_id="u", profile={}, confirmed=True)
    with pytest.raises(ValidationError):
        ProposalCommitRequest(user_id="u", confirmation_text="CONFIRM-123456")


def test_proposal_summary_never_exposes_confirmation_secret() -> None:
    service = WebPaperTradingApplicationService(output_dir="outputs", db_path=None)
    summary = service._proposal_summary(
        {
            "plan_id": "plan-abcdef123456",
            "intent": "capital_change",
            "confirmation_token": "super-secret-token",
            "plan_hash": "private-plan-hash",
            "proposed_changes": [{"amount": 1000}],
        }
    )
    encoded = json.dumps(present_write_result(summary), ensure_ascii=False)
    nested = service._strip_write_secrets({
        "data": {
            "confirmation_token": "super-secret-token",
            "plan_hash": "private-plan-hash",
            "plan_id": "plan-abcdef123456",
        }
    })
    nested_encoded = json.dumps(present_write_result(nested), ensure_ascii=False)
    assert "super-secret-token" not in encoded + nested_encoded
    assert "private-plan-hash" not in encoded + nested_encoded
    assert summary["confirmation_phrase"] == "CONFIRM-123456"


def test_backfill_commit_is_rejected_outside_task_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("agent.session.pending_action_store")
    module.get_pending_plan = lambda *args, **kwargs: {
        "plan_id": "plan-backfill-123456",
        "intent": "paper_backfill",
        "confirmation_token": "server-only",
    }
    monkeypatch.setitem(sys.modules, "agent.session.pending_action_store", module)
    service = WebPaperTradingApplicationService(output_dir="outputs", db_path=None)
    with pytest.raises(ValueError, match="paper_backfill_requires_task_runtime"):
        service.commit_proposal(
            user_id="u",
            plan_id="plan-backfill-123456",
            confirmation_text="CONFIRM-123456",
            request_id="request-1",
            idempotency_key="idem-1",
        )


def test_new_backfill_task_is_additive_and_registered() -> None:
    contract = json.loads((ROOT / "contracts/stage6/task-contract.json").read_text(encoding="utf-8"))
    manager_source = (ROOT / "server/task_runtime/manager.py").read_text(encoding="utf-8")
    handler_source = (ROOT / "server/task_runtime/handlers.py").read_text(encoding="utf-8")
    assert "paper-trading.backfill" in contract["task_types"]
    assert '"paper-trading.backfill"' in manager_source
    assert 'task_type == "paper-trading.backfill"' in handler_source


def test_task_store_persists_only_recovery_metadata() -> None:
    source = (ROOT / "frontend/src/stores/taskStore.ts").read_text(encoding="utf-8")
    partial = source.split("partialize:", 1)[1]
    assert "activeTaskId" in partial and "lastSequence" in partial
    assert "events: state.events" not in partial
    assert "task: state.task" not in partial


def test_react_write_controls_require_confirmation_and_use_named_actions() -> None:
    task_actions = (ROOT / "frontend/src/components/paper/PaperTaskActions.tsx").read_text(encoding="utf-8")
    profile_form = (ROOT / "frontend/src/components/paper/UserProfileForm.tsx").read_text(encoding="utf-8")
    proposal_panel = (ROOT / "frontend/src/components/paper/ProposalPanel.tsx").read_text(encoding="utf-8")
    for label in ("更新 AI 模拟盘", "运行新闻调整", "手动运行调度器"):
        assert label in task_actions
    assert "Modal.confirm" in task_actions
    assert "Modal.confirm" in profile_form
    assert "confirmation_phrase" in proposal_panel
    assert "paper-trading.backfill" in proposal_panel


def test_paper_sections_are_collapsible_and_layout_scrolls_independently() -> None:
    section_source = (ROOT / "frontend/src/components/paper/PaperSectionCard.tsx").read_text(encoding="utf-8")
    page_source = (ROOT / "frontend/src/pages/paper/PaperTradingPage.tsx").read_text(encoding="utf-8")
    layout_source = (ROOT / "frontend/src/layouts/AppLayout.tsx").read_text(encoding="utf-8")
    css_source = (ROOT / "frontend/src/styles/global.css").read_text(encoding="utf-8")
    for section_key in (
        "account-summary", "task-actions", "user-profile", "asset-curve",
        "paper-records", "risk-diagnostics", "cash-flow", "backfill", "proposals",
    ):
        assert section_key in section_source
    assert "全部展开" in section_source and "全部收起" in section_source
    assert "PaperSectionProvider" in page_source and "PaperSectionControls" in page_source
    assert 'className="app-sider-menu-scroll"' in layout_source
    assert 'className="app-content-scroll"' in layout_source
    assert "overflow-y: auto" in css_source
    assert "html, body, #root { height: 100%; margin: 0; overflow: hidden; }" in css_source

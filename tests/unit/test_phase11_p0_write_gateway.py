from __future__ import annotations

from dataclasses import dataclass

from agent.session.confirmation_manager import create_confirmation_plan
from agent.session.pending_action_store import get_pending_plan
from agent.tool_engine import AGENT_MAIN, OP_PROPOSAL, OP_WRITE, execute_tool, get_tool_registry_v2
from agent.tools.strategy_management_tool import manage_strategy
from agent.write_gateway import execute_confirmed_plan_v2
from agent_control_center_utils import write_agent_fixture
from portfolio.cash_flow import list_cash_flows
from strategies.registry import StrategyManifest, get_strategy_registry


def _register_enabled_strategy(output_dir, db_path) -> StrategyManifest:
    manifest = StrategyManifest(
        strategy_id="test_strategy",
        strategy_name="Test Strategy",
        version="v1",
        source_type="test",
        module_path="tests.fake_strategy",
        class_name="FakeStrategy",
        status="enabled",
        enabled_for_paper_trading=True,
    )
    return get_strategy_registry(output_dir=output_dir, db_path=db_path).register(manifest)


def test_phase11_p0_tools_are_registered_as_proposal_and_write() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "strategy.disable.preview": OP_PROPOSAL,
        "strategy.disable.commit": OP_WRITE,
        "capital.change.preview": OP_PROPOSAL,
        "capital.change.commit": OP_WRITE,
        "backfill.preview": OP_PROPOSAL,
        "backfill.commit": OP_WRITE,
        "approval.confirm_plan": OP_WRITE,
    }
    for name, operation_type in expected.items():
        definition = registry.get(name)
        assert definition is not None
        assert definition.operation_type == operation_type
        if operation_type == OP_WRITE:
            assert definition.requires_approval is True


def test_strategy_disable_generates_proposal_then_gateway_commits(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)
    manifest = _register_enabled_strategy(output_dir, db_path)

    preview = manage_strategy(
        "u1",
        action="disable",
        strategy_id=manifest.strategy_id,
        version=manifest.version,
        output_dir=output_dir,
        db_path=db_path,
    )

    assert preview.success is True
    assert preview.requires_confirmation is True
    assert preview.permission == "preview"
    assert get_strategy_registry(output_dir=output_dir, db_path=db_path).get(manifest.strategy_id, manifest.version).enabled_for_paper_trading is True

    committed = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "u1",
        output_dir=output_dir,
        db_path=db_path,
    )

    assert committed.success is True
    disabled = get_strategy_registry(output_dir=output_dir, db_path=db_path).get(manifest.strategy_id, manifest.version)
    assert disabled is not None
    assert disabled.enabled_for_paper_trading is False
    assert disabled.status == "disabled"


def test_strategy_disable_revalidates_state_change(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)
    manifest = _register_enabled_strategy(output_dir, db_path)
    preview = manage_strategy("u1", action="disable", strategy_id=manifest.strategy_id, version=manifest.version, output_dir=output_dir, db_path=db_path)
    get_strategy_registry(output_dir=output_dir, db_path=db_path).disable(manifest.strategy_id, manifest.version)

    committed = execute_confirmed_plan_v2(preview.data["plan_id"], preview.data["confirmation_token"], "u1", output_dir=output_dir, db_path=db_path)

    assert committed.success is False
    assert "business_state_changed" in committed.errors or "strategy_already_disabled" in committed.errors


def test_capital_change_uses_gateway_and_is_idempotent(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, cash=100000.0)
    preview = execute_tool(
        "capital.change.preview",
        {"user_id": "u1", "flow_type": "deposit", "amount": 5000.0, "effective_date": "2026-06-12"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_MAIN,
    )
    assert preview.success is True
    assert list_cash_flows("u1", output_dir=output_dir, db_path=db_path) == []

    first = execute_confirmed_plan_v2(preview.data["plan_id"], preview.data["confirmation_token"], "u1", output_dir=output_dir, db_path=db_path)
    second = execute_confirmed_plan_v2(preview.data["plan_id"], preview.data["confirmation_token"], "u1", output_dir=output_dir, db_path=db_path)

    assert first.success is True
    assert second.success is False
    assert "already_executed" in second.errors
    flows = list_cash_flows("u1", output_dir=output_dir, db_path=db_path)
    assert len(flows) == 1
    assert flows[0].amount == 5000.0


@dataclass
class _FakeBackfillResult:
    status: str = "success"
    end_date: str = "2026-06-12"
    completed_days: int = 1
    buy_order_count: int = 0
    sell_order_count: int = 0

    def to_dict(self):
        return {
            "status": self.status,
            "end_date": self.end_date,
            "completed_days": self.completed_days,
            "buy_order_count": self.buy_order_count,
            "sell_order_count": self.sell_order_count,
        }


def test_backfill_preview_does_not_execute_until_gateway_confirm(tmp_path, monkeypatch) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, cash=100000.0)
    calls: list[dict] = []

    def fake_backfill(**kwargs):
        calls.append(dict(kwargs))
        return _FakeBackfillResult()

    monkeypatch.setattr("agent.services.write_operation_service.run_paper_trading_backfill", fake_backfill)
    preview = execute_tool(
        "backfill.preview",
        {"user_id": "u1", "start_date": "2026-06-12", "end_date": "2026-06-12", "force": True, "resume": False},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_MAIN,
    )
    assert preview.success is True
    assert calls == []

    committed = execute_confirmed_plan_v2(preview.data["plan_id"], preview.data["confirmation_token"], "u1", output_dir=output_dir, db_path=db_path)

    assert committed.success is True
    assert len(calls) == 1
    assert calls[0]["force"] is True
    assert calls[0]["resume"] is False


def test_write_gateway_rejects_missing_and_unknown_plan(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path)
    missing = execute_confirmed_plan_v2("missing", "token", "u1", output_dir=output_dir, db_path=db_path)
    assert missing.success is False
    assert missing.error_type == "plan_not_found"

    plan = create_confirmation_plan("u1", "unknown_plan", {"operation_type": "unknown"}, output_dir=output_dir, db_path=db_path)
    unknown = execute_confirmed_plan_v2(plan["plan_id"], plan["confirmation_token"], "u1", output_dir=output_dir, db_path=db_path)
    assert unknown.success is False
    assert unknown.error_type == "unsupported_plan_intent"
    assert get_pending_plan("u1", plan["plan_id"], output_dir)["execution_status"] == "pending"


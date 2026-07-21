from __future__ import annotations

from agent.tool_engine import get_tool_registry_v2
from agent.tools.tool_registry import get_tool_registry
from app.pages.ai_agent import (
    STRATEGY_CONFIRM_LABELS,
    _strategy_plan_summary_rows,
    _technical_plan_details,
)


def test_strategy_confirmation_buttons_use_distinct_explicit_labels():
    assert STRATEGY_CONFIRM_LABELS["apply_strategy_implementation"] == (
        "确认应用并注册"
    )
    assert STRATEGY_CONFIRM_LABELS["activate_strategy_binding"] == (
        "确认启用未来策略"
    )
    assert STRATEGY_CONFIRM_LABELS["execute_strategy_position_change"] == (
        "确认执行模拟盘调仓"
    )
    assert len(
        {
            STRATEGY_CONFIRM_LABELS["apply_strategy_implementation"],
            STRATEGY_CONFIRM_LABELS["activate_strategy_binding"],
            STRATEGY_CONFIRM_LABELS[
                "execute_strategy_position_change"
            ],
        }
    ) == 3


def test_strategy_cards_show_required_business_fields_without_token():
    implementation_rows = _strategy_plan_summary_rows(
        {
            "intent": "apply_strategy_implementation",
            "proposed_changes": [
                {
                    "implementation_type": "config",
                    "formal_target": "strategies/configs/u1.json",
                }
            ],
            "diff_hash": "sha256:diff",
            "validation_results": {
                "security": "passed",
                "tests": "passed",
                "backtest": "passed",
            },
        }
    )
    assert {row["label"] for row in implementation_rows} >= {
        "实现路径",
        "准备写入",
        "Diff",
        "安全检查",
        "测试",
        "回测",
        "回滚",
    }

    position_rows = _strategy_plan_summary_rows(
        {
            "intent": "execute_strategy_position_change",
            "target_portfolio": [{"stock_code": "000001"}],
            "orders_preview": [{"side": "buy"}],
            "after_state_preview": {
                "estimated_fee": 1.0,
                "estimated_cash": 100.0,
            },
        }
    )
    assert {row["label"] for row in position_rows} >= {
        "TargetPortfolio",
        "买卖清单",
        "金额/费用",
        "现金",
        "风险变化",
    }

    details = _technical_plan_details(
        {
            "plan_id": "plan_1",
            "confirmation_token": "secret",
            "confirmation_token_hash": "hash",
            "plan_hash": "plan_hash",
        }
    )
    assert details == {"plan_id": "plan_1"}


def test_strategy_audit_tool_is_registered_as_read_only():
    modern = get_tool_registry_v2().get("strategy.get_audit_trace")
    assert modern is not None
    assert modern.operation_type == "read"
    assert modern.permission_scope == "read"

    legacy = get_tool_registry()["strategy.get_audit_trace"]
    assert legacy.read_only is True
    assert legacy.requires_confirmation is False

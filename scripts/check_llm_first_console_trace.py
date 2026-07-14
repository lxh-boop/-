from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.console_trace import (
    console_trace_enabled,
    flow_event,
    flow_trace_enabled,
    trace_event,
)


def main() -> None:
    common_sensitive = {
        "api_key": "must_not_be_printed",
        "confirmation_token": "must_not_be_printed",
        "db_path": r"D:\\stock_daily_app\\agent_quant.db",
        "raw_payload": {"must": "not be printed"},
    }

    flow_event(
        "RULE_HINTS",
        {
            "mode": "business_advisory_hints",
            "authoritative": False,
            "rule_hints": {
                "action": ["recommend"],
                "object": ["portfolio"],
                "constraint": ["more_stable"],
            },
            **common_sensitive,
        },
        run_id="flow-self-test",
    )
    flow_event(
        "LLM_USER_GOAL",
        {
            "user_goal": {
                "goal_summary": "生成更稳健的完整目标组合，不执行",
                "action": "construct",
                "expected_outputs": [
                    "target_portfolio",
                    "current_vs_target",
                    "risk_improvement",
                ],
                "requires_write": False,
                "reason_summary": "用户明确要求推荐完整目标组合。",
            },
            **common_sensitive,
        },
        run_id="flow-self-test",
    )
    flow_event(
        "TASK_PLAN",
        {
            "tasks": [
                {"task_id": "task_1", "capability": "portfolio_state"},
                {"task_id": "task_2", "capability": "portfolio_risk"},
                {"task_id": "task_3", "capability": "user_profile"},
                {"task_id": "task_4", "capability": "ranking"},
                {
                    "task_id": "task_5",
                    "capability": "portfolio.design_target_portfolio",
                    "depends_on": ["task_1", "task_2", "task_3", "task_4"],
                },
            ],
            **common_sensitive,
        },
        run_id="flow-self-test",
    )

    trace_event(
        "console_trace.self_test",
        {
            "enabled": console_trace_enabled(),
            "flow_enabled": flow_trace_enabled(),
            "message": "看到 [AGENT-FLOW] 和 [AGENT-TRACE] 表示两类控制台追踪正常。",
            **common_sensitive,
        },
        run_id="trace-self-test",
    )
    print("LLM-first console decision-flow self-test finished")


if __name__ == "__main__":
    main()

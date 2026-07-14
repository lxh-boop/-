from __future__ import annotations

import json

from app.pages.ai_agent import (
    _build_context_safe_summary,
    _format_context_safe_caption,
    _redact_ui_payload,
    _technical_plan_details,
)
from app.pages.ai_paper_trading import _redact_paper_ui_payload


def _encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def test_context_safe_summary_hides_secret_paths_and_large_objects() -> None:
    result = {
        "run_id": "run_1",
        "runtime": {"trace_id": "trace_1"},
        "orchestration": {"task_results": {"task_1": {"status": "success"}}},
        "context": {
            "phase12_context": {
                "context_id": "context_1",
                "minimal_context": {
                    "context_id": "context_1",
                    "run_id": "run_1",
                    "approval": {
                        "pending_plan_id": "plan_1",
                        "status": "pending",
                        "confirmation_token": "raw-token",
                        "token_present": True,
                    },
                    "artifact_refs": [
                        {
                            "artifact_id": "artifact_1",
                            "artifact_type": "portfolio",
                            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
                        }
                    ],
                },
                "llm_context": {
                    "artifact_context": {
                        "artifact_refs": [
                            {
                                "artifact_id": "artifact_1",
                                "artifact_type": "portfolio",
                                "confirmation_token_hash": "hash",
                            }
                        ]
                    },
                    "approval_context": {
                        "pending_plan_id": "plan_1",
                        "status": "pending",
                        "token_present": True,
                    },
                },
            },
            "context_warnings": ["safe warning"],
        },
        "confirmation_token": "top-level-secret",
        "db_path": r"D:\stock_daily_app\data\agent_quant.db",
    }

    summary = _build_context_safe_summary(result)
    encoded = _encoded(summary)

    assert summary["context_available"] is True
    assert summary["context_id"] == "context_1"
    assert summary["run_id"] == "run_1"
    assert summary["trace_id"] == "trace_1"
    assert summary["current_task_count"] == 1
    assert summary["artifact_ref_count"] == 1
    assert summary["pending_approval_exists"] is True
    assert summary["pending_approval"]["plan_id"] == "plan_1"
    assert "raw-token" not in encoded
    assert "top-level-secret" not in encoded
    assert "confirmation_token" not in encoded
    assert "agent_quant.db" not in encoded
    assert r"D:\stock_daily_app" not in encoded

    caption = _format_context_safe_caption(summary)
    assert "Context safe summary:" in caption
    assert "context_id=context_1" in caption
    assert "run_id=run_1" in caption
    assert "trace_id=trace_1" in caption
    assert "confirmation_token" not in caption
    assert "agent_quant.db" not in caption


def test_context_safe_summary_handles_empty_context() -> None:
    summary = _build_context_safe_summary({})

    assert summary["context_available"] is False
    assert summary["artifact_ref_count"] == 0
    assert summary["pending_approval_exists"] is False
    assert "confirmation_token" not in _encoded(summary)
    assert _format_context_safe_caption(summary) == ""


def test_ui_redactor_keeps_safe_token_metrics_but_hides_secrets_and_stacks() -> None:
    payload = {
        "token_estimate": 123,
        "context_window_token_estimate": 80,
        "confirmation_token": "raw-token",
        "nested": {
            "auth_token": "raw-auth-token",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
            "error": 'Traceback (most recent call last): File "D:\\stock_daily_app\\x.py"',
        },
    }

    redacted = _redact_ui_payload(payload)
    encoded = _encoded(redacted)

    assert redacted["token_estimate"] == 123
    assert redacted["context_window_token_estimate"] == 80
    assert redacted["confirmation_token"] == "***"
    assert redacted["nested"]["auth_token"] == "***"
    assert "raw-token" not in encoded
    assert "raw-auth-token" not in encoded
    assert "agent_quant.db" not in encoded
    assert "Traceback" not in encoded


def test_pending_plan_technical_details_hide_confirmation_material() -> None:
    details = _technical_plan_details(
        {
            "plan_id": "plan_1",
            "confirmation_token": "raw-token",
            "confirmation_token_hash": "hash",
            "plan_hash": "plan-hash",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
            "operation_type": "adjust_position",
        }
    )
    encoded = _encoded(details)

    assert details["plan_id"] == "plan_1"
    assert details["operation_type"] == "adjust_position"
    assert "raw-token" not in encoded
    assert "plan-hash" not in encoded
    assert "agent_quant.db" not in encoded


def test_ai_paper_trading_redactor_hides_confirmation_material() -> None:
    redacted = _redact_paper_ui_payload(
        {
            "plan_id": "plan_1",
            "confirmation_token": "raw-token",
            "confirmation_token_hash": "hash",
            "plan_hash": "plan-hash",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
            "token_estimate": 42,
            "error": 'Traceback (most recent call last): File "D:\\stock_daily_app\\x.py"',
        }
    )
    encoded = _encoded(redacted)

    assert redacted["plan_id"] == "plan_1"
    assert redacted["confirmation_token"] == "***"
    assert redacted["token_estimate"] == 42
    assert "raw-token" not in encoded
    assert "plan-hash" not in encoded
    assert "agent_quant.db" not in encoded
    assert "Traceback" not in encoded

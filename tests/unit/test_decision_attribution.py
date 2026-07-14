from __future__ import annotations

import json
from pathlib import Path

from portfolio.decision_attribution import (
    explain_stock_decision_attribution,
    render_decision_attribution_markdown,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_outputs(root: Path) -> None:
    recommendation = {
        "user_id": "u1",
        "trade_date": "2026-07-01",
        "stock_code": "000001",
        "stock_name": "平安银行",
        "model_name": "chronos_bolt_small",
        "original_rank": 2,
        "original_score": 0.91,
        "news_adjustment": 0.2,
        "user_adjustment": -0.05,
        "ai_reliability_weight": 0.5,
        "effective_news_adjustment": 0.1,
        "combined_adjustment": 0.05,
        "position_adjustment_ratio": 1.05,
        "original_target_weight": 0.08,
        "target_weight": 0.084,
        "current_price": 12.3,
        "reason": "Model score normalized to 0.910. 相关公告支持。",
        "risk_warning": "",
        "evidence_news_ids": ["news_1"],
        "evidence_chunk_ids": ["chunk_1"],
        "triggered_rules": [],
    }
    global_recommendation = dict(recommendation)
    global_recommendation["news_adjustment"] = -0.9
    _write_json(root / "recommendations" / "final_recommendations_latest.json", [global_recommendation])
    _write_json(root / "users" / "u1" / "recommendations" / "final_recommendations_latest.json", [recommendation])

    decision = {
        "decision_id": "paper_decision_1",
        "user_id": "u1",
        "trade_date": "2026-07-01",
        "decision_time": "2026-07-01 15:00:00",
        "stock_code": "000001",
        "stock_name": "平安银行",
        "paper_action": "paper_buy",
        "target_weight": 0.084,
        "current_weight": 0.02,
        "order_quantity": 500,
        "order_amount": 6150,
        "executed_price": 12.3,
        "total_fee": 1.845,
        "net_cash_change": -6151.845,
        "original_rank": 2,
        "original_score": 0.91,
        "news_adjustment": 0.2,
        "user_adjustment": -0.05,
        "effective_news_adjustment": 0.1,
        "combined_adjustment": 0.05,
        "position_adjustment_ratio": 1.05,
        "reason": "模拟盘根据原始 Top10、现金和一手约束生成买入。",
        "risk_warning": "",
        "triggered_rules": "",
        "job_id": "job_1",
        "run_id": "run_1",
        "execution_source": "test",
    }
    _write_json(root / "portfolio" / "u1" / "ai_paper_decisions_latest.json", [decision])

    diagnostics = {
        "strategy_mode": "hierarchical_top10",
        "base_weight_note": "Top1-5 use score 12 and Top6-10 use score 5.",
        "top10_target_ratio": 0.8,
        "minimum_cash_ratio": 0.05,
        "maximum_final_position_weight": 0.3,
        "allocation_details": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "original_rank": 2,
                "base_allocation_score": 12,
                "target_weight": 0.084,
                "final_quantity": 500,
                "one_lot_total_cost": 1230,
            }
        ],
        "lot_execution_rounds": [
            {
                "round_no": 1,
                "candidate_stock_codes": ["000001", "000002"],
                "target_weights_before": {"000001": 0.08},
                "target_weights_after": {"000001": 0.084},
                "redistributed_weights": {"000001": 0.004},
            }
        ],
    }
    _write_json(root / "portfolio" / "u1" / "paper_execution_diagnostics_latest.json", diagnostics)


def test_decision_attribution_uses_user_results_and_preserves_formula_trace(tmp_path: Path) -> None:
    _make_outputs(tmp_path)

    payload = explain_stock_decision_attribution(
        user_id="u1",
        stock_code="000001",
        trade_date="2026-07-01",
        output_dir=tmp_path,
    )

    assert payload["mode"] == "read_only_attribution"
    assert "\\users\\u1\\" in payload["sources"]["recommendation"] or "/users/u1/" in payload["sources"]["recommendation"]
    assert payload["formal_recommendation"]["news_adjustment"] == 0.2
    assert payload["paper_decision"]["paper_action"] == "paper_buy"
    assert payload["allocation_trace"]["diagnostic_items"][0]["base_allocation_score"] == 12
    assert payload["allocation_trace"]["lot_execution_rounds"][0]["redistributed_weight"] == 0.004
    assert payload["evidence_trace"]["evidence_news_ids"] == ["news_1"]
    assert payload["formula_check"]["effective_news_adjustment_matches"] is True
    assert payload["formula_check"]["combined_adjustment_matches"] is True
    assert payload["formula_check"]["position_adjustment_ratio_matches"] is True


def test_decision_attribution_is_read_only(tmp_path: Path) -> None:
    _make_outputs(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())

    explain_stock_decision_attribution("u1", "000001", output_dir=tmp_path)

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    assert after == before


def test_decision_attribution_reports_missing_sources_without_recomputing(tmp_path: Path) -> None:
    payload = explain_stock_decision_attribution("u1", "000001", output_dir=tmp_path)

    assert payload["formal_recommendation"] == {}
    assert payload["paper_decision"] == {}
    assert payload["formula_check"]["status"] == "missing_recommendation"
    assert any("不会重新生成" in warning for warning in payload["warnings"])


def test_decision_attribution_markdown_contains_trace_and_disclaimer(tmp_path: Path) -> None:
    _make_outputs(tmp_path)
    payload = explain_stock_decision_attribution("u1", "000001", output_dir=tmp_path)

    markdown = render_decision_attribution_markdown(payload)

    assert "000001" in markdown
    assert "news_1" in markdown
    assert "只读取已保存结果" in markdown
    assert "不构成投资建议" in markdown

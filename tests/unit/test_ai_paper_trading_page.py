from app import classic_services
from app.classic_services import load_paper_trading_snapshot
from app.pages import ai_paper_trading


def test_ai_paper_trading_page_sections_and_title() -> None:
    assert ai_paper_trading.AI_PAPER_TRADING_PAGE_TITLE == "AI 模拟盘"
    sections = ai_paper_trading.get_ai_paper_trading_page_sections()
    assert sections[0] == "用户与账户摘要"
    assert "用户画像与初始资产" in sections
    assert "每日交易策略设置" not in sections
    assert "资金分配详情" in sections
    assert "账户资产走势" in sections
    assert sections[-1] == "组合风险"


def test_ai_paper_trading_read_models_are_cached() -> None:
    assert hasattr(ai_paper_trading._cached_paper_trading_snapshot, "clear")
    assert hasattr(ai_paper_trading._cached_ai_reliability_state, "clear")
    assert hasattr(ai_paper_trading._cached_paper_cash_flows, "clear")
    assert callable(ai_paper_trading.clear_ai_paper_trading_page_cache)


def test_ai_paper_trading_action_table_uses_chinese_labels() -> None:
    table = ai_paper_trading.build_today_action_table(
        [
            {
                "stock_code": "1",
                "stock_name": "A",
                "paper_action": "paper_buy",
                "target_weight": 0.05,
                "current_weight": 0.0,
                "order_amount": 1000,
                "order_quantity": 100,
                "news_adjustment": 0.0,
                "user_adjustment": 0.0,
                "effective_news_adjustment": 0.0,
                "combined_adjustment": 0.0,
                "position_adjustment_ratio": 1.0,
                "reason": "paper reason",
                "risk_warning": "",
            }
        ]
    )

    assert not table.empty
    assert "来源动作" not in table.columns
    assert table.iloc[0]["模拟盘执行"] == "买入"
    assert table.iloc[0]["综合调整"] == 0.0
    assert table.iloc[0]["股票代码"] == "000001"


def test_ai_paper_trading_empty_csv_files_do_not_crash(tmp_path) -> None:
    root = tmp_path / "portfolio" / "u1"
    root.mkdir(parents=True)
    (root / "paper_positions_latest.csv").write_text("", encoding="utf-8")
    (root / "paper_orders_latest.csv").write_text("", encoding="utf-8")

    snapshot = load_paper_trading_snapshot("u1", output_dir=tmp_path)

    assert snapshot["positions"].empty
    assert snapshot["orders"].empty
    assert ai_paper_trading._read_csv(root / "paper_positions_latest.csv").empty


def test_allocation_detail_tables_are_chinese() -> None:
    diagnostics = {
        "total_asset": 100000,
        "reserved_cash": 5000,
        "planned_investable_cash": 95000,
        "released_budget": 1000,
        "redistributed_cash": 800,
        "capital_utilization_rate": 0.8,
        "allocation_details": [
            {
                "stock_code": "1",
                "stock_name": "A",
                "final_rank": 1,
                "final_score": 0.9,
                "ideal_target_weight": 0.08,
                "initial_target_amount": 8000,
                "initial_quantity": 100,
                "final_quantity": 200,
                "final_weight": 0.01,
                "one_lot_total_cost": 501,
                "released_budget": 0,
                "received_redistribution": 500,
            }
        ],
    }

    summary = ai_paper_trading.build_allocation_summary_table(diagnostics)
    detail = ai_paper_trading.build_allocation_detail_table(diagnostics)
    assert not summary.empty
    assert summary.columns.tolist() == ["项目", "数值"]
    assert detail.iloc[0]["股票代码"] == "000001"


def test_user_profile_payload_maps_initial_capital_to_available_capital() -> None:
    payload = ai_paper_trading.build_user_profile_payload(
        "u1",
        {
            "initial_capital": 123456,
            "risk_level": "C3 稳健型",
            "investment_horizon": "3-6个月",
        },
    )

    assert payload["user_id"] == "u1"
    assert payload["initial_capital"] == 123456
    assert payload["available_capital"] == 123456


def test_ai_paper_trading_strategy_is_fixed_hierarchical_top10() -> None:
    assert ai_paper_trading.FIXED_PAPER_STRATEGY == {
        "strategy": "hierarchical_top10",
        "top_k": 15,
        "entry_top_k": 10,
        "hold_buffer_rank": 15,
        "max_positions": 10,
    }


def test_ai_paper_backfill_service_imports_real_pipeline(tmp_path) -> None:
    assert classic_services.run_ai_paper_backfill.__name__ == "run_paper_trading_backfill"
    assert classic_services.load_paper_backfill_status("missing-user", output_dir=tmp_path) == {}

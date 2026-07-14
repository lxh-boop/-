from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from database.repositories import NewsRepository
from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def write_benchmark_fixture(
    *,
    output_dir: str | Path,
    db_path: str | Path,
    user_id: str,
    setup: dict[str, Any] | None = None,
) -> None:
    setup = dict(setup or {})
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stock_code = str(setup.get("stock_code") or "600519").zfill(6)
    stock_name = str(setup.get("stock_name") or "Kweichow Moutai")
    secondary_code = str(setup.get("secondary_code") or "000001").zfill(6)
    secondary_name = str(setup.get("secondary_name") or "Ping An Bank")
    price = float(setup.get("price") or 100.0)
    secondary_price = float(setup.get("secondary_price") or 12.0)

    if setup.get("with_ranking", True):
        pd.DataFrame(
            [
                {"rank": 1, "date": "2026-06-12", "code": stock_code, "name": stock_name, "close": price, "score": 0.91, "confidence": "high"},
                {"rank": 2, "date": "2026-06-12", "code": secondary_code, "name": secondary_name, "close": secondary_price, "score": 0.72, "confidence": "medium"},
                {"rank": 3, "date": "2026-06-12", "code": "300750", "name": "CATL", "close": 180.0, "score": 0.68, "confidence": "medium"},
            ]
        ).to_csv(output_path / "ranking_latest.csv", index=False, encoding="utf-8-sig")

    if setup.get("with_recommendations", True):
        rec_dir = output_path / "users" / user_id / "recommendations"
        rec_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "trade_date": "2026-06-12",
                    "current_price": price,
                    "original_score": 0.91,
                    "final_score": 0.84,
                    "final_action": "keep",
                    "news_adjustment": -0.03,
                    "effective_news_adjustment": -0.03,
                    "user_adjustment": 0.0,
                    "combined_adjustment": -0.03,
                    "target_weight": 0.12,
                    "position_adjustment_ratio": 0.97,
                    "ai_reliability_weight": 0.2,
                    "risk_warning": "",
                    "triggered_rules": "[]",
                    "evidence_news_ids": "[\"news_600519_1\"]",
                    "evidence_chunk_ids": "[]",
                    "reason": "benchmark fixture",
                },
                {
                    "stock_code": secondary_code,
                    "stock_name": secondary_name,
                    "trade_date": "2026-06-12",
                    "current_price": secondary_price,
                    "original_score": 0.72,
                    "final_score": 0.70,
                    "final_action": "keep",
                    "news_adjustment": 0.0,
                    "effective_news_adjustment": 0.0,
                    "user_adjustment": 0.0,
                    "combined_adjustment": 0.0,
                    "target_weight": 0.05,
                    "position_adjustment_ratio": 1.0,
                    "ai_reliability_weight": 0.2,
                    "risk_warning": "",
                    "triggered_rules": "[]",
                    "evidence_news_ids": "[]",
                    "evidence_chunk_ids": "[]",
                    "reason": "benchmark fixture",
                },
            ]
        ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")

    storage = PortfolioStorage(db_path, output_dir=output_path / "portfolio" / user_id)
    if setup.get("with_account", True):
        account = create_default_account(user_id, initial_cash=float(setup.get("cash") or 100000.0))
        storage.save_account(account)
        positions = []
        if setup.get("with_positions", True):
            positions = [
                create_position(
                    user_id=user_id,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    quantity=200.0,
                    cost_price=price,
                    current_price=price,
                    total_assets=float(account.total_assets),
                    industry="Consumer",
                ),
                create_position(
                    user_id=user_id,
                    stock_code=secondary_code,
                    stock_name=secondary_name,
                    quantity=1000.0,
                    cost_price=secondary_price,
                    current_price=secondary_price,
                    total_assets=float(account.total_assets),
                    industry="Bank",
                ),
            ]
        storage.save_positions(positions)

    if setup.get("with_news", False):
        repo = NewsRepository(db_path)
        repo.insert_news_event(
            {
                "news_id": "news_600519_1",
                "title": "Benchmark fixture: channel inventory pressure eased",
                "summary": "A fixture news event used for repeatable agent evaluation.",
                "content": "The benchmark fixture reports a moderate operational update for the mapped stock.",
                "source": "fixture",
                "publish_time": "2026-06-12 10:00:00",
                "trade_date": "2026-06-12",
                "event_type": "operations",
                "sentiment": "neutral",
                "importance_score": 0.6,
                "is_announcement": 0,
                "url": "fixture://news_600519_1",
                "content_hash": "fixture_news_600519_1",
                "retention_level": "hot",
                "is_major_event": 0,
                "is_used_by_agent": 0,
                "raw_content_saved": 0,
            }
        )
        repo.insert_news_stock_mapping(
            {
                "mapping_id": "mapping_600519_1",
                "news_id": "news_600519_1",
                "stock_code": stock_code,
                "stock_name": stock_name,
                "industry": "Consumer",
                "relevance_score": 0.9,
                "impact_direction": "neutral",
                "impact_strength": 0.2,
                "impact_confidence": 0.8,
                "mapping_method": "fixture",
                "evidence_text": "benchmark fixture mapping",
            }
        )

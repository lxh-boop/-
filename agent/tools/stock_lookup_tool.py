from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools._common import dataframe_records, first_present, normalize_stock_code, safe_int


def _recommendation_paths(user_id: str, output_dir: str | Path) -> list[Path]:
    root = Path(output_dir)
    return [
        root / "users" / str(user_id) / "recommendations" / "final_recommendations_latest.csv",
        root / "recommendations" / "final_recommendations_latest.csv",
        root / "final_recommendations_latest.csv",
    ]


def load_latest_ranking(output_dir: str | Path = "outputs") -> list[dict[str, Any]]:
    return dataframe_records(Path(output_dir) / "ranking_latest.csv")


def load_latest_recommendations(user_id: str = "default", output_dir: str | Path = "outputs") -> list[dict[str, Any]]:
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for path in _recommendation_paths(user_id, output_dir):
        for row in dataframe_records(path):
            code = normalize_stock_code(first_present(row, ["stock_code", "code"], ""))
            key = f"{path}:{code}:{first_present(row, ['trade_date', 'date'], '')}"
            if key in seen:
                continue
            seen.add(key)
            records.append(row)
        if records:
            break
    return records


def _row_code(row: dict[str, Any]) -> str:
    return normalize_stock_code(first_present(row, ["stock_code", "code", "ts_code"], ""))


def _row_name(row: dict[str, Any]) -> str:
    return str(first_present(row, ["stock_name", "name", "asset_name"], ""))


def find_stock_row(records: list[dict[str, Any]], stock_query: str) -> dict[str, Any] | None:
    query = str(stock_query or "").strip()
    query_code = normalize_stock_code(query)
    if query_code:
        for row in records:
            if _row_code(row) == query_code:
                return row
    if query:
        for row in records:
            if query in _row_name(row):
                return row
    return None


def lookup_stock(
    stock_query: str,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    # Compatibility wrapper. Agent default path is market.lookup_stock via ToolExecutor.
    # planned_removal_phase=post_phase11_1_legacy_cleanup
    from agent.services.market_analysis_service import market_analysis_service

    return market_analysis_service.lookup_stock(
        stock_query,
        user_id=user_id,
        output_dir=output_dir,
    )

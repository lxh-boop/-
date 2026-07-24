from __future__ import annotations

from app.services.model_search_results import (
    BACKTEST_DISCLAIMER,
    BACKTEST_MASTER_TABLE_PATH,
    MODEL_CANDIDATES_PATH,
    MODEL_DISCOVERY_REPORT_PATH,
    MODEL_SEARCH_ERRORS_PATH,
    MODEL_SEARCH_RESULTS_PATH,
    SELECTED_STRATEGY_PATH,
    format_strategy_option,
    load_daily_returns_for_strategy,
    load_selected_strategy,
    load_table_file,
    make_strategy_from_row,
    resolve_output_path,
    save_selected_strategy,
)


def load_model_discovery_report() -> str:
    if not MODEL_DISCOVERY_REPORT_PATH.exists():
        return ""
    return MODEL_DISCOVERY_REPORT_PATH.read_text(encoding="utf-8", errors="ignore")

__all__ = [
    "BACKTEST_DISCLAIMER",
    "BACKTEST_MASTER_TABLE_PATH",
    "MODEL_CANDIDATES_PATH",
    "MODEL_DISCOVERY_REPORT_PATH",
    "MODEL_SEARCH_ERRORS_PATH",
    "MODEL_SEARCH_RESULTS_PATH",
    "SELECTED_STRATEGY_PATH",
    "format_strategy_option",
    "load_daily_returns_for_strategy",
    "load_model_discovery_report",
    "load_selected_strategy",
    "load_table_file",
    "make_strategy_from_row",
    "resolve_output_path",
    "save_selected_strategy",
]

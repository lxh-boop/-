from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT_DIR / "data"
MODELS_DIR = ROOT_DIR / "models"
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOGS_DIR = ROOT_DIR / "logs"
EXTERNAL_REPOS_DIR = ROOT_DIR / "external_repos"

MODEL_DISCOVERY_DIR = OUTPUTS_DIR / "model_discovery"
MODEL_CANDIDATES_PATH = MODEL_DISCOVERY_DIR / "model_candidates.csv"
MODEL_CANDIDATES_JSON_PATH = MODEL_DISCOVERY_DIR / "model_candidates.json"
MODEL_DISCOVERY_REPORT_PATH = MODEL_DISCOVERY_DIR / "model_discovery_report.md"
MODEL_DOWNLOAD_LOG_PATH = MODEL_DISCOVERY_DIR / "model_download_log.csv"
MODEL_TRAIN_LOG_PATH = MODEL_DISCOVERY_DIR / "model_train_log.csv"
MODEL_DISCOVERY_ERRORS_PATH = MODEL_DISCOVERY_DIR / "errors.csv"

BACKTEST_DIR = OUTPUTS_DIR / "backtests"
BACKTEST_DAILY_RETURNS_DIR = BACKTEST_DIR / "daily_returns"
BACKTEST_PREDICTIONS_DIR = BACKTEST_DIR / "predictions"
BACKTEST_METRICS_DIR = BACKTEST_DIR / "metrics"
BACKTEST_MASTER_TABLE_PATH = BACKTEST_DIR / "backtest_master_table.csv"

MODEL_SEARCH_DIR = OUTPUTS_DIR / "model_search"
MODEL_SEARCH_RESULTS_PATH = MODEL_SEARCH_DIR / "search_results.csv"
MODEL_SEARCH_ERRORS_PATH = MODEL_SEARCH_DIR / "search_errors.csv"
MODEL_SEARCH_REPORT_PATH = MODEL_SEARCH_DIR / "model_search_report.md"
SELECTED_STRATEGY_PATH = MODEL_SEARCH_DIR / "selected_strategy.json"


def project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path

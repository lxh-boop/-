from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from pandas.errors import PerformanceWarning


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kronos_runtime.stock_direction_features import build_stock_direction_dataset


DEFAULT_PREDICTIONS = (
    ROOT
    / "outputs"
    / "backtests"
    / "predictions"
    / "target_full_recent_v1_kronos_mini_t1_predictions.csv"
)
DEFAULT_MARKET_HISTORY = ROOT / "data" / "kronos_market_history.csv"
DEFAULT_FEATURE_DIR = ROOT / "data" / "model_precision" / "tushare"
DEFAULT_OUTPUT = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v7_events.parquet"
)
DEFAULT_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v7_events.txt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the causal stock-level feature panel for Top15 evaluation."
    )
    parser.add_argument("--prediction-history", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--market-history", type=Path, default=DEFAULT_MARKET_HISTORY)
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--columns-output", type=Path, default=DEFAULT_COLUMNS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    warnings.filterwarnings("ignore", category=PerformanceWarning)
    frame, columns = build_stock_direction_dataset(
        prediction_history_path=args.prediction_history,
        market_history_path=args.market_history,
        tushare_feature_dir=args.feature_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    args.columns_output.write_text("\n".join(columns) + "\n", encoding="utf-8")
    print(
        f"saved rows={len(frame)} features={len(columns)} "
        f"date={frame['date'].min().date()}..{frame['date'].max().date()} "
        f"to {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

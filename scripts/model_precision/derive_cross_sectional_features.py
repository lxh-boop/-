from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
)
DEFAULT_INPUT_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
)
DEFAULT_OUTPUT = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v6_cross.parquet"
)
DEFAULT_OUTPUT_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v6_cross.txt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add causal daily cross-sectional and industry-relative ranks."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--input-columns", type=Path, default=DEFAULT_INPUT_COLUMNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-columns", type=Path, default=DEFAULT_OUTPUT_COLUMNS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = pd.read_parquet(args.input)
    base_columns = [
        value
        for value in args.input_columns.read_text(encoding="utf-8").splitlines()
        if value in frame.columns
    ]
    prefixes = (
        "alpha_",
        "basic_",
        "flow_",
        "margin_",
        "prior_",
        "relative_",
        "stock_",
        "tech_",
    )
    candidates = [
        column
        for column in frame.columns
        if column.startswith(prefixes)
        and not column.startswith("cross_pct_")
        and pd.api.types.is_numeric_dtype(frame[column])
    ]
    print(f"daily cross-sectional rank columns={len(candidates)}", flush=True)
    ranks = frame.groupby("date", sort=False)[candidates].rank(
        pct=True, method="average"
    )
    ranks.columns = [f"cross_all_pct_{column}" for column in candidates]
    additions = [ranks.astype("float32")]

    industry_candidates = [
        column
        for column in candidates
        if column.startswith(("alpha_", "flow_", "tech_"))
    ]
    if "industry" in frame.columns and industry_candidates:
        print(f"industry-relative rank columns={len(industry_candidates)}", flush=True)
        industry_ranks = frame.groupby(["date", "industry"], sort=False)[
            industry_candidates
        ].rank(pct=True, method="average")
        industry_ranks.columns = [
            f"industry_pct_{column}" for column in industry_candidates
        ]
        additions.append(industry_ranks.astype("float32"))

    expanded = pd.concat([frame, *additions], axis=1)
    new_columns = [column for addition in additions for column in addition.columns]
    feature_columns = list(dict.fromkeys([*base_columns, *new_columns]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    expanded.to_parquet(args.output, index=False)
    args.output_columns.write_text(
        "\n".join(feature_columns) + "\n", encoding="utf-8"
    )
    print(
        f"saved rows={len(expanded)} features={len(feature_columns)} to {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

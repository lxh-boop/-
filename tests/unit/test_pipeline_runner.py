from __future__ import annotations

from pipelines.pipeline_runner import build_parser, context_from_args


def test_pipeline_runner_builds_context_from_cli_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--user-id",
            "u1",
            "--trade-date",
            "2026-06-11",
            "--top-k",
            "20",
            "--stock-pool",
            "csi300",
            "--paper-trading",
            "--dry-run",
            "--steps",
            "prediction,rag",
        ]
    )
    context = context_from_args(args)

    assert context.user_id == "u1"
    assert context.trade_date == "2026-06-11"
    assert context.top_k == 20
    assert context.paper_trading_enabled is True
    assert context.dry_run is True
    assert args.steps == "prediction,rag"

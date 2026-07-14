from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pipelines.schemas import (
    PaperTradingPipelineResult,
    PipelineContext,
    PipelineStatus,
    PredictionPipelineResult,
    RAGPipelineResult,
    ReportPipelineResult,
    SignalFusionPipelineResult,
)


COMPLIANCE_TEXT = (
    "本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目展示，"
    "不构成投资建议，不承诺收益，不用于实盘自动交易，真实交易必须由用户自行判断并确认，"
    "回测和模拟盘结果不代表未来收益。"
)


def _date_token(trade_date: str) -> str:
    return str(trade_date or "latest").replace("-", "")


def _adjustment_counts(scoring_result: SignalFusionPipelineResult | None) -> Counter:
    counter = Counter()
    for output in (scoring_result.fusion_outputs if scoring_result else []):
        value = float(getattr(output, "combined_adjustment", 0.0) or 0.0)
        if value > 0:
            counter["positive"] += 1
        elif value < 0:
            counter["negative"] += 1
        else:
            counter["neutral"] += 1
    return counter


def _paper_action_counts(paper_result: PaperTradingPipelineResult | None) -> Counter:
    counter = Counter()
    for order in (paper_result.orders if paper_result else []):
        counter[getattr(order, "action", "unknown")] += 1
    if not counter and paper_result and paper_result.plan:
        for decision in paper_result.plan.decisions:
            counter[getattr(decision, "action", "unknown")] += 1
    return counter


def run_report_pipeline(
    context: PipelineContext,
    prediction_result: PredictionPipelineResult | None = None,
    rag_result: RAGPipelineResult | None = None,
    scoring_result: SignalFusionPipelineResult | None = None,
    paper_result: PaperTradingPipelineResult | None = None,
    output_dir: str | Path | None = None,
) -> ReportPipelineResult:
    output_dir = Path(output_dir) if output_dir else context.resolved_output_dir() / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    adjustment_counts = _adjustment_counts(scoring_result)
    paper_counts = _paper_action_counts(paper_result)
    warnings: list[str] = []
    for result in [prediction_result, rag_result, scoring_result, paper_result]:
        if result:
            warnings.extend(result.warnings)

    risk_summary = "No portfolio risk summary available."
    if paper_result and paper_result.plan and paper_result.plan.risk_warnings:
        risk_summary = "; ".join(paper_result.plan.risk_warnings)

    trade_date = context.trade_date
    if prediction_result and prediction_result.predictions:
        trade_date = prediction_result.predictions[0].trade_date or trade_date
    report_path = output_dir / f"daily_pipeline_report_{_date_token(trade_date)}.md"
    text = "\n".join(
        [
            f"# Daily Pipeline Report - {trade_date}",
            "",
            f"- User: {context.user_id}",
            f"- Model: {context.model_name} / {context.model_version}",
            f"- Dry run: {context.dry_run}",
            f"- Paper trading enabled: {context.paper_trading_enabled}",
            "",
            "## Counts",
            f"- Model predictions: {prediction_result.output_count if prediction_result else 0}",
            f"- RAG evidence: {rag_result.output_count if rag_result else 0}",
            "",
            "## Scoring Numeric Adjustments",
            f"- positive: {adjustment_counts.get('positive', 0)}",
            f"- neutral: {adjustment_counts.get('neutral', 0)}",
            f"- negative: {adjustment_counts.get('negative', 0)}",
            "",
            "## Paper Trading Actions",
            *[f"- {action}: {count}" for action, count in sorted(paper_counts.items())],
            "",
            "## Portfolio Risk Summary",
            risk_summary,
            "",
            "## Main Risk Warnings",
            *(f"- {warning}" for warning in warnings),
            "",
            "## Compliance",
            COMPLIANCE_TEXT,
            "",
        ]
    )
    report_path.write_text(text, encoding="utf-8")
    return ReportPipelineResult(
        status=PipelineStatus.SUCCESS,
        message=f"Generated daily pipeline report: {report_path}",
        input_count=sum(result.output_count for result in [prediction_result, rag_result, scoring_result, paper_result] if result),
        output_count=1,
        output_paths={"report": str(report_path)},
        report_path=str(report_path),
        report_text=text,
    )

from __future__ import annotations

from typing import Callable

from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.prediction_pipeline import run_prediction_pipeline
from pipelines.rag_pipeline import run_rag_pipeline
from pipelines.report_pipeline import run_report_pipeline
from pipelines.schemas import BasePipelineResult, DailyUpdatePipelineResult, PipelineContext, PipelineStatus
from pipelines.signal_fusion_pipeline import run_signal_fusion_pipeline


STEP_ALIASES = {
    "prediction": "prediction",
    "rag": "rag",
    "scoring": "scoring",
    "signal": "scoring",
    "paper": "paper",
    "paper_trading": "paper",
    "report": "report",
}


def _normalize_steps(steps: list[str] | str | None) -> list[str]:
    if steps is None:
        return ["prediction", "rag", "scoring", "paper", "report"]
    raw = steps.split(",") if isinstance(steps, str) else steps
    result = []
    for step in raw:
        normalized = STEP_ALIASES.get(str(step).strip(), str(step).strip())
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _failed_step(step: str, message: str) -> DailyUpdatePipelineResult:
    return DailyUpdatePipelineResult(
        status=PipelineStatus.FAILED,
        message=message,
        errors=[message],
        step_results={step: BasePipelineResult(status=PipelineStatus.FAILED, message=message, errors=[message])},
    )


def run_daily_update_pipeline(
    context: PipelineContext,
    steps: list[str] | str | None = None,
    prediction_fn: Callable = run_prediction_pipeline,
    rag_fn: Callable = run_rag_pipeline,
    scoring_fn: Callable = run_signal_fusion_pipeline,
    paper_fn: Callable = run_paper_trading_pipeline,
    report_fn: Callable = run_report_pipeline,
) -> DailyUpdatePipelineResult:
    selected = _normalize_steps(steps)
    results: dict[str, BasePipelineResult] = {}
    predictions = []
    evidence = []
    recommendations = []

    if "prediction" in selected:
        result = prediction_fn(context)
        results["prediction"] = result
        if result.status != PipelineStatus.SUCCESS:
            return DailyUpdatePipelineResult(
                status=PipelineStatus.FAILED,
                message=f"prediction step failed: {result.message}",
                input_count=0,
                output_count=0,
                errors=result.errors,
                warnings=result.warnings,
                step_results=results,
            )
        predictions = result.predictions

    if "rag" in selected:
        if not predictions:
            return _failed_step("rag", "rag step requires prediction outputs.")
        result = rag_fn(context, predictions)
        results["rag"] = result
        if result.status == PipelineStatus.FAILED:
            return DailyUpdatePipelineResult(
                status=PipelineStatus.FAILED,
                message=f"rag step failed: {result.message}",
                errors=result.errors,
                warnings=result.warnings,
                step_results=results,
            )
        evidence = result.evidence

    if "scoring" in selected:
        if not predictions:
            return _failed_step("scoring", "scoring step requires prediction outputs.")
        result = scoring_fn(context, predictions, evidence)
        results["scoring"] = result
        if result.status != PipelineStatus.SUCCESS:
            return DailyUpdatePipelineResult(
                status=PipelineStatus.FAILED,
                message=f"scoring step failed: {result.message}",
                errors=result.errors,
                warnings=result.warnings,
                step_results=results,
            )
        recommendations = result.recommendations

    if "paper" in selected:
        if not recommendations:
            return _failed_step("paper", "paper step requires scoring recommendations.")
        result = paper_fn(context, recommendations)
        results["paper"] = result
        if result.status == PipelineStatus.FAILED:
            return DailyUpdatePipelineResult(
                status=PipelineStatus.FAILED,
                message=f"paper step failed: {result.message}",
                errors=result.errors,
                warnings=result.warnings,
                step_results=results,
            )

    if "report" in selected:
        result = report_fn(
            context,
            prediction_result=results.get("prediction"),
            rag_result=results.get("rag"),
            scoring_result=results.get("scoring"),
            paper_result=results.get("paper"),
        )
        results["report"] = result

    output_paths = {}
    for name, result in results.items():
        for key, value in result.output_paths.items():
            output_paths[f"{name}.{key}"] = value
    warnings = [warning for result in results.values() for warning in result.warnings]
    errors = [error for result in results.values() for error in result.errors]
    return DailyUpdatePipelineResult(
        status=PipelineStatus.SUCCESS if not errors else PipelineStatus.PARTIAL,
        message=f"Completed pipeline steps: {', '.join(results)}",
        input_count=sum(result.input_count for result in results.values()),
        output_count=sum(result.output_count for result in results.values()),
        output_paths=output_paths,
        errors=errors,
        warnings=warnings,
        step_results=results,
    )

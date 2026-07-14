from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.ragas_eval.answer_adapter import ProjectAnswerAdapter, answer_metadata
from evaluation.ragas_eval.config import RagasEvalConfig
from evaluation.ragas_eval.dataset_loader import load_jsonl_dataset
from evaluation.ragas_eval.financial_metrics import calculate_financial_metrics
from evaluation.ragas_eval.rag_adapter import ProjectRagAdapter
from evaluation.ragas_eval.ragas_metrics import id_metrics_with_optional_ragas, llm_metrics_with_optional_ragas
from evaluation.ragas_eval.result_exporter import export_results
from evaluation.ragas_eval.retrieval_metrics import calculate_retrieval_metrics
from evaluation.ragas_eval.schemas import CaseRunResult, EvaluationCase


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _output_dir(base: str | Path, experiment_name: str) -> Path:
    return Path(base) / experiment_name / _timestamp()


class RagasEvalRunner:
    def __init__(
        self,
        config: RagasEvalConfig,
        *,
        rag_adapter: ProjectRagAdapter | None = None,
        answer_adapter: ProjectAnswerAdapter | None = None,
    ) -> None:
        self.config = config
        self.rag_adapter = rag_adapter
        self.answer_adapter = answer_adapter or ProjectAnswerAdapter()

    def _ensure_rag_adapter(self) -> ProjectRagAdapter:
        if self.rag_adapter is None:
            self.rag_adapter = ProjectRagAdapter()
        return self.rag_adapter

    def run_case(self, case: EvaluationCase, *, mode: str, no_llm: bool = False) -> CaseRunResult:
        started = time.perf_counter()
        result = CaseRunResult(case=case, warnings=list(case.warnings))
        try:
            if mode in {"retrieval", "answer", "all"}:
                result.stage = "retrieval"
                contexts, retrieval_meta = self._ensure_rag_adapter().retrieve(case, top_k=self.config.top_k)
                result.retrieved_contexts = contexts
                result.warnings.extend(retrieval_meta.get("warnings") or [])
                for context in contexts:
                    result.warnings.extend([f"{context.chunk_id}: {item}" for item in context.warnings])
                result.metrics.update({
                    "retrieval_latency_ms": retrieval_meta.get("latency_ms", 0.0),
                    "adapter_chunk_count": retrieval_meta.get("chunk_count", 0),
                })

            if mode in {"answer", "all"}:
                result.stage = "answer"
                answer = self.answer_adapter.generate(case, result.retrieved_contexts)
                if answer.error:
                    raise RuntimeError(answer.error)
                result.response = answer.response
                result.cited_chunk_ids = answer.cited_chunk_ids
                result.answer_metadata = answer_metadata(answer)
                result.answer_metadata.update(
                    {
                        "response_source": case.response_source or "diagnostic_generated_evidence_summary",
                        "response_run_id": case.response_run_id,
                        "uses_captured_actual_response": bool(case.actual_response),
                    }
                )

            result.stage = "metrics"
            retrieved_ids = [item.chunk_id for item in result.retrieved_contexts]
            result.metrics.update(
                calculate_retrieval_metrics(
                    retrieved_ids,
                    case.reference_context_ids,
                    k_values=self.config.k_values,
                )
            )
            result.metrics.update(id_metrics_with_optional_ragas(retrieved_ids, case.reference_context_ids))
            evaluated_response = str(result.answer_metadata.get("evaluated_response") or result.response)
            result.metrics.update(calculate_financial_metrics(case, result.retrieved_contexts, response=evaluated_response))
            if mode in {"answer", "all"}:
                result.metrics.update(
                    llm_metrics_with_optional_ragas(
                        case,
                        result.retrieved_contexts,
                        response=evaluated_response,
                        runtime=self.config.runtime,
                        no_llm=no_llm,
                    )
                )
            result.stage = "done"
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return result

    def run(
        self,
        *,
        dataset: str | Path,
        output_dir: str | Path = Path("outputs") / "ragas_eval",
        mode: str | None = None,
        limit: int | None = None,
        case_id: str | None = None,
        no_llm: bool = False,
        fail_fast: bool = False,
    ) -> tuple[Path, dict[str, Any]]:
        run_mode = mode or self.config.mode
        start_time = datetime.now().astimezone()
        loaded = load_jsonl_dataset(dataset, case_id=case_id, limit=limit, fail_fast=fail_fast)
        run_results: list[CaseRunResult] = []
        failed_cases: list[dict[str, Any]] = []
        for case in loaded.cases:
            item = self.run_case(case, mode=run_mode, no_llm=no_llm)
            run_results.append(item)
            if item.error:
                failed_cases.append({
                    "case_id": case.case_id,
                    "stage": item.stage,
                    "exception_type": item.error.split(":", 1)[0],
                    "error": item.error,
                    "retryable": True,
                })
                if fail_fast:
                    break
        end_time = datetime.now().astimezone()
        target_dir = _output_dir(output_dir, self.config.experiment_name)
        return export_results(
            output_dir=target_dir,
            config=self.config,
            results=run_results,
            failed_cases=failed_cases,
            dataset_errors=loaded.errors,
            dataset_warnings=loaded.warnings,
            start_time=start_time,
            end_time=end_time,
        )

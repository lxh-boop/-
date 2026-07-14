from __future__ import annotations

import time
from typing import Any

from evaluation.ragas_eval.response_normalizer import normalize_response_for_ragas
from evaluation.ragas_eval.schemas import AnswerResult, EvaluationCase, RetrievedContext
from scoring.schemas import COMPLIANCE_DISCLAIMER


class ProjectAnswerAdapter:
    """Offline answer adapter using the existing Agent stock-RAG summary style."""

    prompt_version = "production_stock_rag_summary_v1"
    model_name = "deterministic_agent_stock_rag_summary"

    def generate(
        self,
        case: EvaluationCase,
        contexts: list[RetrievedContext],
    ) -> AnswerResult:
        started = time.perf_counter()
        try:
            if case.actual_response:
                return AnswerResult(
                    response=case.actual_response,
                    cited_chunk_ids=[str(item) for item in case.metadata.get("response_cited_chunk_ids", [])],
                    model_name=str(case.metadata.get("response_model") or "production_agent_captured_response"),
                    prompt_version=str(case.metadata.get("response_prompt_version") or "production_agent_runtime"),
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    token_usage=dict(case.metadata.get("response_token_usage") or {}),
                )
            lines = [f"共找到 {len(contexts)} 条 RAG 证据。"]
            for context in contexts[:5]:
                snippet = str(context.text or "").replace("\n", " ").strip()[:180]
                lines.append(f"- [{context.chunk_id}] {snippet}")
            lines.append(COMPLIANCE_DISCLAIMER)
            return AnswerResult(
                response="\n".join(lines).strip(),
                cited_chunk_ids=[item.chunk_id for item in contexts[:5]],
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                token_usage={},
            )
        except Exception as exc:
            return AnswerResult(
                response="",
                cited_chunk_ids=[],
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                token_usage={},
                error=f"{type(exc).__name__}: {exc}",
            )


def answer_metadata(answer: AnswerResult) -> dict[str, Any]:
    normalized = normalize_response_for_ragas(answer.response)
    return {
        "model_name": answer.model_name,
        "prompt_version": answer.prompt_version,
        "evaluated_response": normalized.evaluated_response,
        "normalization_method": normalized.normalization_method,
        "removed_text": normalized.removed_text,
        "removed_formatting": normalized.removed_formatting,
        "evaluated_response_policy": (
            "Ragas metrics use the actual response after deterministic removal "
            "of fixed non-business boilerplate only."
        ),
        "latency_ms": answer.latency_ms,
        "token_usage": answer.token_usage,
        "error": answer.error,
    }

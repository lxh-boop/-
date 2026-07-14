from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from database.repositories import NewsRepository
from pipelines.schemas import PipelineContext, PipelineStatus, RAGPipelineResult
from rag.hybrid_retriever import HybridRetriever
from rag.retrieval_logger import RetrievalLogger
from rag.schemas import RagChunk
from scoring.schemas import ModelPredictionSignal, NewsEvidenceSignal


def _load_chunks(context: PipelineContext) -> list[RagChunk]:
    try:
        repo = NewsRepository(context.db_path)
        trade_date = None if context.trade_date == "latest" else context.trade_date
        rows = repo.list_news_chunks(trade_date=trade_date)
        return [RagChunk.from_mapping(row) for row in rows]
    except Exception:
        return []


def _query_for_prediction(prediction: ModelPredictionSignal) -> str:
    parts = [prediction.stock_code, prediction.stock_name, prediction.industry, "news risk event"]
    return " ".join(part for part in parts if part)


def _evidence_from_result(result, prediction: ModelPredictionSignal) -> NewsEvidenceSignal:
    meta = dict(result.metadata or {})
    return NewsEvidenceSignal(
        news_id=str(result.news_id or meta.get("news_id") or ""),
        stock_code=prediction.stock_code,
        impact_direction=str(meta.get("impact_direction") or "neutral"),
        impact_strength=float(meta.get("impact_strength") or meta.get("importance_score") or 0.0),
        impact_confidence=float(meta.get("impact_confidence") or meta.get("mapping_confidence") or 0.5),
        mapping_confidence=float(meta.get("mapping_confidence") or 0.5),
        importance_score=float(meta.get("importance_score") or 0.5),
        evidence_chunk_ids=[result.chunk_id],
        publish_time=str(meta.get("publish_time") or ""),
        trade_date=str(meta.get("trade_date") or prediction.trade_date),
        evidence_text=result.chunk_text,
    )


def _resolve_rag_workers(max_workers: int | None, task_count: int) -> int:
    if task_count <= 0:
        return 1
    if max_workers is None:
        env_value = os.environ.get("RAG_PIPELINE_WORKERS", "").strip()
        if env_value:
            try:
                max_workers = int(float(env_value))
            except ValueError:
                max_workers = None
    if max_workers is None:
        max_workers = min(4, task_count)
    return max(1, min(int(max_workers), task_count))


def _search_for_prediction(
    retriever: HybridRetriever,
    prediction: ModelPredictionSignal,
    context: PipelineContext,
    final_top_k: int,
) -> dict[str, Any]:
    query = _query_for_prediction(prediction)
    filters = {
        "stock_code": prediction.stock_code,
        "decision_time": context.decision_time,
        "trade_date_end": prediction.trade_date or context.trade_date,
    }
    try:
        results = retriever.search(query, final_top_k=final_top_k, metadata_filter=filters)
        return {
            "prediction": prediction,
            "query": query,
            "filters": filters,
            "results": list(results or []),
            "error": "",
        }
    except Exception as exc:
        return {
            "prediction": prediction,
            "query": query,
            "filters": filters,
            "results": [],
            "error": f"RAG search failed for {prediction.stock_code}: {exc}",
        }


def run_rag_pipeline(
    context: PipelineContext,
    predictions: list[ModelPredictionSignal],
    chunks: list[RagChunk | dict[str, Any]] | None = None,
    retriever: HybridRetriever | None = None,
    final_top_k: int = 3,
    max_workers: int | None = None,
) -> RAGPipelineResult:
    if not predictions:
        return RAGPipelineResult(
            status=PipelineStatus.SKIPPED,
            message="No predictions supplied to RAG pipeline.",
            input_count=0,
            output_count=0,
            evidence=[],
            retrieval_ids=[],
        )

    chunk_objects = [chunk if isinstance(chunk, RagChunk) else RagChunk.from_mapping(chunk) for chunk in (chunks if chunks is not None else _load_chunks(context))]
    retriever = (retriever or HybridRetriever()).build_index(chunk_objects)
    logger = RetrievalLogger(context.db_path)
    evidence: list[NewsEvidenceSignal] = []
    retrieval_ids: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    worker_count = _resolve_rag_workers(max_workers, len(predictions))

    if worker_count <= 1:
        search_rows = [
            _search_for_prediction(retriever, prediction, context, final_top_k)
            for prediction in predictions
        ]
    else:
        rows_by_index: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(_search_for_prediction, retriever, prediction, context, final_top_k): index
                for index, prediction in enumerate(predictions)
            }
            for future in as_completed(future_map):
                rows_by_index[future_map[future]] = future.result()
        search_rows = [rows_by_index[index] for index in range(len(predictions)) if index in rows_by_index]

    for row in search_rows:
        prediction = row["prediction"]
        query = row["query"]
        filters = row["filters"]
        results = row["results"]
        if row.get("error"):
            errors.append(str(row["error"]))
        result_dicts = [item.to_dict() for item in results]
        try:
            retrieval_id = logger.log_retrieval(
                query=query,
                query_type="daily_pipeline_stock_news",
                trade_date=prediction.trade_date or context.trade_date,
                decision_time=context.decision_time,
                filters=filters,
                bm25_results=result_dicts,
                dense_results=[],
                rerank_results=result_dicts,
                returned_chunk_ids=[item.chunk_id for item in results],
                used_chunk_ids=[],
                user_id=context.user_id,
                stock_code=prediction.stock_code,
            )
            retrieval_ids.append(retrieval_id)
        except Exception as exc:
            warnings.append(f"failed to write rag_retrieval_log for {prediction.stock_code}: {exc}")
        evidence.extend(_evidence_from_result(item, prediction) for item in results)

    status = PipelineStatus.FAILED if errors and not retrieval_ids else PipelineStatus.SUCCESS
    return RAGPipelineResult(
        status=status,
        message=f"Retrieved {len(evidence)} RAG evidence items.",
        input_count=len(predictions),
        output_count=len(evidence),
        errors=errors,
        warnings=warnings,
        evidence=evidence,
        retrieval_ids=retrieval_ids,
    )

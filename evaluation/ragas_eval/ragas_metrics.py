from __future__ import annotations

import asyncio
from importlib import metadata
from typing import Any

from evaluation.ragas_eval.config import RagasEvalRuntimeConfig
from evaluation.ragas_eval.retrieval_metrics import id_context_precision, id_context_recall
from evaluation.ragas_eval.schemas import EvaluationCase, RetrievedContext

_PROMPT_CACHE: dict[tuple[str, str, str, bool], Any] = {}


def get_ragas_version() -> str:
    try:
        return metadata.version("ragas")
    except metadata.PackageNotFoundError:
        return "not_installed"


def ragas_is_installed() -> bool:
    return get_ragas_version() != "not_installed"


def _run_async(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(awaitable)
    if loop.is_running():
        # CLI paths are synchronous. If this helper is ever called from an
        # already-running loop, fail loudly instead of silently nesting loops.
        raise RuntimeError("Ragas async scoring cannot run inside an active event loop")
    return loop.run_until_complete(awaitable)


def _score_value(result: Any) -> float | None:
    if isinstance(result, dict):
        for key in ["score", "value"]:
            if key in result and result[key] is not None:
                return float(result[key])
    if hasattr(result, "score"):
        return float(result.score)
    if isinstance(result, int | float):
        return float(result)
    return None


def _is_deepseek_v4(runtime: RagasEvalRuntimeConfig) -> bool:
    text = f"{runtime.base_url} {runtime.model}".lower()
    return "deepseek" in text and "v4" in text


def _build_ragas_llm(runtime: RagasEvalRuntimeConfig) -> tuple[Any, dict[str, Any]]:
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    extra_body = {"thinking": {"type": "disabled"}} if _is_deepseek_v4(runtime) else None
    chat = ChatOpenAI(
        api_key=runtime.api_key,
        base_url=runtime.base_url or None,
        model=runtime.model,
        temperature=runtime.temperature,
        timeout=runtime.timeout_seconds,
        max_retries=runtime.retry_count,
        extra_body=extra_body,
    )
    return LangchainLLMWrapper(chat), {
        "llm_wrapper": "LangchainLLMWrapper",
        "llm_client": "langchain_openai.ChatOpenAI",
        "deepseek_v4_thinking_disabled": bool(extra_body),
    }


def _build_ragas_embeddings(runtime: RagasEvalRuntimeConfig) -> tuple[Any, dict[str, Any]]:
    if not runtime.embedding_model:
        raise RuntimeError(
            "RAGAS_EVAL_EMBEDDING_MODEL 未配置；Answer Relevancy 已跳过，"
            "不能使用字符 n-gram 或其他非语义 embedding 代替。"
        )
    model_name = str(runtime.embedding_model or "").strip()
    if model_name.startswith("local:"):
        from ragas.embeddings import HuggingFaceEmbeddings

        local_model_name = model_name.removeprefix("local:").strip()
        if not local_model_name:
            raise RuntimeError("local Ragas embedding model name is empty")
        embeddings = HuggingFaceEmbeddings(
            model=local_model_name,
            use_api=False,
            device="cpu",
            normalize_embeddings=True,
        )
        return embeddings, {
            "embedding_wrapper": "ragas.embeddings.HuggingFaceEmbeddings",
            "embedding_client": "sentence_transformers.SentenceTransformer",
            "embedding_backend": "local_sentence_transformers",
            "embedding_model_name": local_model_name,
        }

    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    embeddings = OpenAIEmbeddings(
        api_key=runtime.api_key,
        base_url=runtime.base_url or None,
        model=model_name,
        timeout=runtime.timeout_seconds,
        max_retries=runtime.retry_count,
    )
    return LangchainEmbeddingsWrapper(embeddings), {
        "embedding_wrapper": "LangchainEmbeddingsWrapper",
        "embedding_client": "langchain_openai.OpenAIEmbeddings",
        "embedding_backend": "openai_compatible",
        "embedding_model_name": model_name,
    }


def _prompt_cache_key(metric_name: str, prompt_attr: str, runtime: RagasEvalRuntimeConfig) -> tuple[str, str, str, bool]:
    return (
        metric_name,
        prompt_attr,
        runtime.judge_language,
        bool(runtime.adapt_prompt_instruction),
    )


def _adapt_prompt_once(metric: Any, prompt_attr: str, llm: Any, runtime: RagasEvalRuntimeConfig) -> str:
    if not runtime.adapt_prompts or not runtime.judge_language:
        return "not_requested"
    prompt = getattr(metric, prompt_attr, None)
    if prompt is None or not hasattr(prompt, "adapt"):
        return "not_supported"
    key = _prompt_cache_key(type(metric).__name__, prompt_attr, runtime)
    if key not in _PROMPT_CACHE:
        _PROMPT_CACHE[key] = _run_async(
            prompt.adapt(
                target_language=runtime.judge_language,
                llm=llm,
                adapt_instruction=runtime.adapt_prompt_instruction,
            )
        )
    setattr(metric, prompt_attr, _PROMPT_CACHE[key])
    return "adapted"


def _adapt_metric_prompts(metric: Any, llm: Any, runtime: RagasEvalRuntimeConfig) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for prompt_attr in [
        "context_precision_prompt",
        "context_recall_prompt",
        "nli_statements_prompt",
        "statement_generator_prompt",
        "question_generation",
    ]:
        if hasattr(metric, prompt_attr):
            try:
                statuses[prompt_attr] = _adapt_prompt_once(metric, prompt_attr, llm, runtime)
            except Exception as exc:
                statuses[prompt_attr] = f"failed:{type(exc).__name__}: {exc}"
    return statuses


def id_metrics_with_optional_ragas(retrieved_ids: list[str], reference_ids: list[str]) -> dict[str, Any]:
    fallback = {
        "id_context_precision": id_context_precision(retrieved_ids, reference_ids),
        "id_context_recall": id_context_recall(retrieved_ids, reference_ids),
        "id_context_metric_backend": "custom_deterministic",
        "ragas_version": get_ragas_version(),
        "metric_api": "custom_deterministic",
    }
    if not ragas_is_installed() or not reference_ids:
        return fallback

    try:
        from ragas import SingleTurnSample
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall

        sample = SingleTurnSample(
            user_input="id based retrieval evaluation",
            retrieved_context_ids=list(retrieved_ids),
            reference_context_ids=list(reference_ids),
        )
        precision_metric = IDBasedContextPrecision()
        recall_metric = IDBasedContextRecall()
        precision = _score_value(_run_async(precision_metric.single_turn_ascore(sample)))
        recall = _score_value(_run_async(recall_metric.single_turn_ascore(sample)))
        return {
            "id_context_precision": precision,
            "id_context_recall": recall,
            "id_context_metric_backend": "ragas",
            "ragas_version": get_ragas_version(),
            "metric_api": "collections",
        }
    except Exception as exc:
        payload = dict(fallback)
        payload["id_context_metric_backend"] = "custom_deterministic"
        payload["ragas_id_metric_error"] = f"{type(exc).__name__}: {exc}"
        return payload


def llm_metrics_with_optional_ragas(
    case: EvaluationCase,
    contexts: list[RetrievedContext],
    *,
    response: str,
    runtime: RagasEvalRuntimeConfig,
    no_llm: bool = False,
) -> dict[str, Any]:
    base = {
        "ragas_version": get_ragas_version(),
        "metric_api": "collections",
        "llm_metric_status": "skipped",
        "llm_metric_reason": "",
    }
    if no_llm or runtime.no_llm:
        base["llm_metric_reason"] = "--no-llm enabled"
        return base
    if not ragas_is_installed():
        base["llm_metric_reason"] = "当前未安装 Ragas，请执行：python -m pip install ragas"
        return base
    if not runtime.api_key or not runtime.model:
        base["llm_metric_reason"] = "RAGAS_EVAL_API_KEY/RAGAS_EVAL_MODEL 未配置；LLM-based 指标已跳过"
        return base
    if not response:
        base["llm_metric_reason"] = "response empty; LLM-based metrics skipped"
        return base

    try:
        from ragas import SingleTurnSample
        from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy

        llm, llm_metadata = _build_ragas_llm(runtime)
        sample = SingleTurnSample(
            user_input=case.user_input,
            response=response,
            reference=case.reference or None,
            retrieved_contexts=[item.text for item in contexts],
        )

        metrics: dict[str, Any] = {
            "llm_metric_status": "success",
            "llm_metric_reason": "",
            "ragas_version": get_ragas_version(),
            "metric_api": "collections",
            "judge_language": runtime.judge_language,
            "prompt_adaptation": {},
            **llm_metadata,
        }
        estimated_calls = 0
        if case.reference:
            context_precision = LLMContextPrecisionWithReference(llm=llm)
            context_recall = LLMContextRecall(llm=llm)
            metrics["prompt_adaptation"]["context_precision"] = _adapt_metric_prompts(context_precision, llm, runtime)
            metrics["prompt_adaptation"]["context_recall"] = _adapt_metric_prompts(context_recall, llm, runtime)
            metrics["context_precision"] = _score_value(_run_async(context_precision.single_turn_ascore(sample)))
            metrics["context_recall"] = _score_value(_run_async(context_recall.single_turn_ascore(sample)))
            estimated_calls += 2
        else:
            metrics["context_precision"] = None
            metrics["context_recall"] = None
            metrics["context_reference_metric_status"] = "skipped_no_reference"

        faithfulness = Faithfulness(llm=llm)
        metrics["prompt_adaptation"]["content_faithfulness"] = _adapt_metric_prompts(faithfulness, llm, runtime)
        metrics["content_faithfulness"] = _score_value(_run_async(faithfulness.single_turn_ascore(sample)))
        metrics["faithfulness_scope"] = "evaluated_response_after_deterministic_boilerplate_removal"
        estimated_calls += 2
        try:
            embeddings, embedding_metadata = _build_ragas_embeddings(runtime)
            metrics.update(embedding_metadata)
            response_relevancy = ResponseRelevancy(
                llm=llm,
                embeddings=embeddings,
                strictness=max(1, int(runtime.response_relevancy_strictness)),
            )
            metrics["prompt_adaptation"]["response_relevancy"] = _adapt_metric_prompts(response_relevancy, llm, runtime)
            response_relevancy_score = _score_value(_run_async(response_relevancy.single_turn_ascore(sample)))
            metrics["response_relevancy"] = response_relevancy_score
            metrics["answer_relevancy"] = response_relevancy_score
            metrics["answer_relevancy_status"] = "success"
            estimated_calls += max(1, int(runtime.response_relevancy_strictness))
        except Exception as exc:
            metrics["response_relevancy"] = None
            metrics["answer_relevancy"] = None
            metrics["answer_relevancy_status"] = "skipped_no_real_embedding"
            metrics["answer_relevancy_reason"] = f"{type(exc).__name__}: {exc}"
        metrics["ragas_estimated_llm_call_count"] = float(estimated_calls)
        return metrics
    except Exception as exc:
        payload = dict(base)
        payload["llm_metric_status"] = "failed"
        payload["llm_metric_reason"] = f"{type(exc).__name__}: {exc}"
        return payload

# Ragas 离线评测指南

免责声明：本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 作用范围

`evaluation/ragas_eval/` 为股票新闻 RAG 和 Agent 回答提供离线评测能力。它只在用户显式运行 CLI 时加载，不进入 Streamlit 初始化、每日更新、新闻下载、Agent 实时问答、模拟盘更新或仓位计算链路。

当前接入方式：

- 真实检索入口：`rag.hybrid_retriever.HybridRetriever`
- 日更 RAG 入口：`pipelines/rag_pipeline.py`
- Agent 轻量 RAG 工具：`agent/tools/stock_rag_tool.py` 和 `agent/rag_tool.py`
- Reranker：`rag/reranker.py`，安装 `sentence-transformers` 且 CrossEncoder 可用时启用，否则按 `hybrid_score` fallback
- LLM 客户端：`llm_client.LLMClient`
- 新闻 chunk：`rag/schemas.py::RagChunk` 与 SQLite `news_chunk`

现有 chunk 字段中有 `chunk_id`、`news_id`、`stock_code`、`publish_time`、`source`、`trade_date`、`event_type`、`section_title`。当前数据库没有独立 `document_id`、`parent_id`、`event_id`、`title` 列，因此评测 Adapter 会：

- 将 `news_id` 兼容为 `document_id`
- `parent_id/event_id` 缺失时写入 warning
- `title` 缺失时使用 `section_title`
- 不凭空生成不存在的新闻、事件 ID 或标准答案

## 依赖

Ragas 是可选离线依赖。未安装时不影响 App、日更、Agent、模拟盘和普通测试。

安装方式：

```powershell
python -m pip install -r requirements-ragas.txt
```

如果只运行确定性指标，不需要安装 Ragas：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_template.jsonl `
  --config configs/ragas_eval/retrieval_only.yaml `
  --experiment-name smoke_test `
  --mode retrieval `
  --no-llm
```

当前本机已验证的组合：

```text
ragas==0.3.9
langchain-community==0.3.31
langchain-openai==1.3.3
langchain-core==1.4.8
```

说明：`ragas 0.3.9` 导入时会引用 `langchain_community.chat_models.vertexai`，`langchain-community 0.4.x` 已移除该模块，因此本项目将 `langchain-community` 固定在 `0.3.31`。

## 评测模型配置

LLM-based 指标可能产生 API 费用，也可能把评测样本发送到配置的模型服务。默认不调用外部模型。

可选环境变量：

```text
RAGAS_EVAL_PROVIDER
RAGAS_EVAL_MODEL
RAGAS_EVAL_API_KEY
RAGAS_EVAL_BASE_URL
RAGAS_EVAL_EMBEDDING_MODEL
RAGAS_EVAL_TEMPERATURE
RAGAS_EVAL_TIMEOUT_SECONDS
RAGAS_EVAL_MAX_WORKERS
RAGAS_EVAL_JUDGE_LANGUAGE
RAGAS_EVAL_ADAPT_PROMPTS
RAGAS_EVAL_ADAPT_PROMPT_INSTRUCTION
RAGAS_EVAL_RESPONSE_RELEVANCY_STRICTNESS
```

日志和输出只记录是否配置 API Key，不记录密钥原文。

如果未显式设置 `RAGAS_EVAL_*`，离线评测会复用 APP 本地配置中的 LLM API Key、Base URL 和模型名，并在输出中只记录 `base_url_domain`。

Embedding：

- 设置 `RAGAS_EVAL_EMBEDDING_MODEL` 时，使用 OpenAI-compatible embedding endpoint。
- 未设置时，Answer/Response Relevancy 明确跳过。不能使用字符 n-gram 或其他非语义 embedding 冒充 Ragas Answer Relevancy。

## 数据集

模板文件：

```text
data/evaluation/rag_eval_template.jsonl
```

正式评测集建议：

```text
data/evaluation/rag_eval_cases.jsonl
```

字段说明：

```json
{
  "case_id": "rag_case_001",
  "user_input": "宁德时代近期是否存在股东减持风险？",
  "stock_code": "300750.SZ",
  "decision_time": "2026-06-20T15:00:00+08:00",
  "reference": "人工审核后的参考答案，可为空",
  "reference_context_ids": ["chunk_001"],
  "allowed_related_stock_codes": [],
  "tags": ["stock_direct_event"],
  "metadata": {"source": "manual"}
}
```

要求：

- `case_id` 唯一。
- `decision_time` 必须带时区。
- `reference` 为空时跳过依赖参考答案的 LLM 指标。
- `reference_context_ids` 为空时跳过 ID recall/precision 的参考集合判断。
- 不要把模型自动答案当成未经审核的金标准。

## 自动诊断种子集

如果还没有人工评测集，可以先从本地 SQLite `news_chunk` 生成诊断集：

```powershell
python -m evaluation.ragas_eval.seed_dataset `
  --limit 3 `
  --output data/evaluation/rag_eval_auto_seed.jsonl
```

这个文件使用本地真实新闻 chunk，`reference_context_ids` 来自原始 chunk_id，`reference` 来自 chunk 文本摘录。它只用于接入诊断，输出中标记为 `gold_level=diagnostic_not_human_gold`，不能替代人工金标准。

## 指标

不需要 LLM 的指标：

- ID-Based Context Precision
- ID-Based Context Recall
- Recall@K、Precision@K、HitRate@K
- MRR、nDCG@K
- `future_leak_rate`
- `wrong_stock_rate`
- `duplicate_event_rate`
- `direct_evidence_rate`

需要 Ragas 与评测模型的指标：

- Context Precision
- Context Recall
- Content Faithfulness
- Response Relevancy

`unsupported_position_reason_rate` 第一版只在无法可靠获得逐主张证据时返回 `not_available`，不会用关键词伪造精确数值。

## 运行

确定性检索评测：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_cases.jsonl `
  --config configs/ragas_eval/retrieval_only.yaml `
  --experiment-name baseline_hybrid `
  --mode retrieval `
  --no-llm
```

完整评测：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_cases.jsonl `
  --config configs/ragas_eval/full_rag_eval.yaml `
  --experiment-name hybrid_reranker_full `
  --mode all
```

中文 prompt 适配实验：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_auto_seed.jsonl `
  --config configs/ragas_eval/full_rag_eval_chinese_adapt.yaml `
  --experiment-name chinese_prompt_adapt_probe `
  --mode all `
  --limit 1
```

注意：Ragas prompt adaptation 会先调用评测 LLM 翻译 prompt examples。本机实测该步骤在 DeepSeek judge 上可能超过 10 分钟，因此常规 `full_rag_eval.yaml` 默认关闭 `adapt_prompts`，只保留中文样本内容直接评测。

调试单条样本：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_cases.jsonl `
  --config configs/ragas_eval/retrieval_only.yaml `
  --case-id rag_case_001 `
  --limit 1 `
  --no-llm
```

## 输出

每次实验写入：

```text
outputs/ragas_eval/<experiment_name>/<timestamp>/
```

包含：

- `summary.json`
- `case_results.csv`
- `case_results.jsonl`
- `failed_cases.jsonl`
- `quality_gate_report.json`
- `experiment_report.md`
- `run_config_snapshot.yaml`
- `environment.json`

`case_results.jsonl` 保留完整上下文、metadata、response 和指标；CSV 适合快速浏览。

## 实验对比

```powershell
python -m evaluation.ragas_eval.compare_experiments `
  --baseline outputs/ragas_eval/baseline/.../summary.json `
  --candidate outputs/ragas_eval/candidate/.../summary.json
```

输出：

- `experiment_comparison.md`
- `experiment_comparison.csv`

对比内容包括 Recall@5、Recall@10、MRR、nDCG@10、ID 指标、Ragas LLM 指标、金融业务指标和 P95 latency，并列出共同成功、回退和恢复的样本集合。

## 常见错误

- `当前未安装 Ragas`：运行 `python -m pip install -r requirements-ragas.txt`，或加 `--no-llm` 只跑确定性指标。
- `decision_time must include timezone`：把时间写成 `2026-06-20T15:00:00+08:00`。
- `reference_context_ids must be a list`：即使为空也要写 `[]`。
- 质量门槛失败：结果仍会保留，CLI 返回非零退出码；不要自动修改生产配置。
- Ragas 导入时报 `langchain_community.chat_models.vertexai` 缺失：安装 `requirements-ragas.txt` 中固定的兼容版本。
- 进程退出时出现 `multiprocess.resource_tracker` ignored exception：这是当前 Ragas 依赖链在 Windows/Python 3.12 下的退出期兼容噪声，当前实测不影响结果文件和退出码。

## 本机真实 Ragas 验证

已运行：

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_auto_seed.jsonl `
  --config configs/ragas_eval/full_rag_eval.yaml `
  --experiment-name auto_seed_content_faithfulness_no_fake_embedding `
  --mode all `
  --limit 1
```

输出目录：

```text
outputs/ragas_eval/auto_seed_content_faithfulness_no_fake_embedding/20260629_133737
```

关键结果：

```text
Context Precision: 0.9999999999666667
Context Recall: 1.0
Content Faithfulness: 1.0
Answer/Response Relevancy: skipped_no_real_embedding
Recall@10: 1.0
MRR: 1.0
future_leak_rate: 0.0
wrong_stock_rate: 0.0
acceptance_eligible: false
```

说明：这次使用的是自动诊断种子集，因此不能作为真实质量验收；未配置真实 embedding，因此 Answer/Reponse Relevancy 跳过，不输出伪分数。

Judge 观察：

- `evaluated_response` 必须由 `response` 经过 `deterministic_boilerplate_removal` 得到，只能删除固定免责声明、固定状态文本、纯格式字符。
- 不能删除或修改投资结论、新闻影响判断、仓位调整原因、风险判断、时间、金额、比例、涨跌判断。
- Ragas Faithfulness 在输出中命名为 `content_faithfulness`，表示“确定性清理后的实际回答内容”的忠实度，不代表完整 UI 文本的忠实度。

## 费用与隐私

- `--no-llm` 不调用外部评测模型。
- LLM-based 指标可能产生费用。
- 默认评测结果保存在本地。
- API Key 不写入代码、日志或输出文件。

# RAG Retrieval Foundation

`rag/` 是证据检索基础层。RAG 只负责找证据，不直接给投资建议，不直接决定买入、卖出、降权或剔除。

## 组件职责

| 模块 | 职责 |
|---|---|
| `chunkers.py` | 新闻、公告、Agent 决策日志、行业规则和 Agent 规则切 chunk |
| `metadata_filter.py` | 股票、行业、事件、发布时间、交易日、公告等 metadata 过滤，避免未来新闻 |
| `bm25_retriever.py` | 关键词检索，召回股票名、代码和事件词相关 chunk |
| `dense_retriever.py` | 语义检索；显式记录 `embedding_model_name`、`embedding_dimension`、`index_version`、`load_error` 和 `fallback_reason` |
| `hybrid_retriever.py` | BM25 + Dense 合并去重，使用 RRF 融合后进入 reranker TopK |
| `reranker.py` | 精排；缺少 cross-encoder 时按 hybrid_score fallback |
| `retrieval_logger.py` | 写入 `rag_retrieval_log` 并更新 chunk 检索计数 |
| `retention_policy.py` | 新闻生命周期策略 |
| `index_store.py` | 索引保存和加载 |

## 未来函数控制

检索必须使用 `publish_time <= decision_time` 和交易日范围过滤。盘后新闻不能用于当天盘中或收盘前决策。

## 可选依赖

第一版 BM25 内置轻量实现；如安装 `jieba` 可获得更好的中文分词。Dense 和 reranker 依赖 `sentence-transformers` 时才启用，否则自动 fallback，不影响 BM25/Hybrid 测试。

## Phase 0/1 Commands

```powershell
py scripts\resync_news_rag.py --from-cache --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00"
py -m evaluation.news_rag_diagnostics --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00" --require-dense
```

Detailed baseline and handoff notes:

- `docs/IMPROVEMENT_BASELINE.md`
- `docs/handoff/01_NEWS_RAG_DENSE_RETRIEVAL.md`

## 日志

每次检索应写入 `rag_retrieval_log`，包括 query、filters、BM25/Dense/Rerank 返回结果、返回 chunk 和 Agent 使用 chunk。被 Agent 使用过的证据应通过 `evidence_snapshot` 长期保留。

免责声明：本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目作品集展示。不构成投资建议。不承诺收益。不用于实盘自动交易。

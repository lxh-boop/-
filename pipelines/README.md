# Pipeline Integration Foundation

`pipelines/` is the Stage 4 fixed workflow layer. It is not an Agent and does not perform complex question answering. It only calls existing modules in a deterministic order:

1. Read model predictions / ranking.
2. Retrieve RAG evidence.
3. Run `scoring/` Signal Fusion.
4. Run `portfolio/` paper trading.
5. Write database logs.
6. Output reports and recommendations.

## Boundaries

- RAG only provides evidence.
- Scoring only outputs constrained post-processing actions.
- Portfolio only performs paper trading.
- Real trading is isolated and not connected.
- Existing entry points such as `daily_incremental_update.py` and `agent/report_agent.py` remain unchanged.

## CLI

```powershell
python -m pipelines.pipeline_runner --user-id default --trade-date latest --top-k 50 --dry-run
```

Optional steps:

```powershell
python -m pipelines.pipeline_runner --steps prediction,rag,scoring,paper,report
```

# Phase 2 Handoff: Unified System Monitoring

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 2 adds a read-only monitoring layer for the five linked layers:

```text
data -> model -> RAG -> Agent -> portfolio
```

It records why the system is healthy, degraded, or critical without changing strategy, ranking, RAG parameters, prompts, portfolio holdings, or Agent execution behavior.

The four legacy Agent files were not modified:

```text
agent/portfolio_qa_agent.py
agent/event_impact_agent.py
agent/portfolio_review_agent.py
agent/model_monitor_agent.py
```

## Modified Files

- `app.py`: adds the top-level `系统监控` page using lazy import before homepage ranking load.
- `app/pages/system_monitor.py`: Streamlit monitoring page with metrics, alerts, versions, history, and save-snapshot action.
- `evaluation/system_monitor.py`: metric collection, alert evaluation, snapshot builder, and persistence entrypoints.
- `scripts/run_system_monitor_snapshot.py`: CLI to collect and persist a monitoring snapshot.
- `configs/system_monitor_thresholds.json`: configurable `normal/warning/critical` alert thresholds.
- `database/migrations/017_system_monitor.sql`: snapshot and alert tables.
- `database/repositories/system_monitor_repository.py`: repository for monitor snapshots and alerts.
- `database/repositories/__init__.py`: exports `SystemMonitorRepository`.
- `database/table_registry.py`: primary-key registry entries for new tables.
- `tests/unit/test_system_monitor.py`: migration, repository, snapshot, idempotency, missing-module, and no-business-write tests.
- `tests/unit/test_app_top_level_pages.py`: verifies the new page remains lazy-loaded and dispatches before ranking load.
- Documentation indexes updated in `README.md`, `PROJECT_STRUCTURE.md`, `PROJECT_FILE_DIRECTORY.md`, `database/README.md`, `docs/AGENT_USAGE.md`, and `docs/IMPROVEMENT_BASELINE.md`.

## Database Migration

New migration:

```text
database/migrations/017_system_monitor.sql
```

New tables:

```text
system_monitor_snapshots
system_monitor_alerts
```

Snapshot fields include `trade_date`, `user_id`, `data_version`, `model_version`, `rag_index_version`, `run_id`, `portfolio_snapshot_id`, five JSON metric groups, version info, missing modules, and timestamps.

Alert fields include `snapshot_id`, `layer`, `metric_name`, `severity`, `metric_value`, `threshold_value`, and message.

## Config

Alert rules are configured in:

```text
configs/system_monitor_thresholds.json
```

The first version covers:

- data full-text coverage
- feature NaN ratio
- RAG empty-result rate
- RAG source traceability
- Agent failed-run rate
- portfolio max drawdown
- single-stock concentration

Rules are data-only. The monitor never switches models, changes strategy, edits prompts, changes RAG parameters, or trades.

## Commands

Generate and persist a monitor snapshot:

```powershell
py scripts\run_system_monitor_snapshot.py --db-path data\agent_quant.db --output-dir outputs --user-id cht --trade-date 2026-07-01 --report-path runtime\system_monitor_ui\cht_snapshot_after_fix.json
```

Development UI:

```powershell
py -m streamlit run app.py --server.port 8503 --server.address 127.0.0.1 --server.headless true
```

## Test Results

Compilation:

```powershell
py -m compileall evaluation\system_monitor.py scripts\run_system_monitor_snapshot.py app\pages\system_monitor.py tests\unit\test_system_monitor.py
```

Result: passed.

Focused Phase 2 tests:

```powershell
py -m pytest tests\unit\test_system_monitor.py tests\unit\test_app_top_level_pages.py -q
```

Result: `7 passed in 10.97s`.

Database/RAG regression:

```powershell
py -m pytest tests\unit\test_database_schema.py tests\unit\test_database_repositories.py tests\unit\test_rag_dense_retriever.py tests\unit\test_rag_hybrid_retriever.py -q
```

Result: `8 passed in 61.12s`. A Python `multiprocess.resource_tracker` exit-time warning appeared after pytest completed; the test result was still successful.

Agent runtime safety regression:

```powershell
py -m pytest tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_write_requires_confirmation.py -q
```

Result: `4 passed in 22.55s`.

## Page Verification

Verified in the in-app browser against:

```text
http://127.0.0.1:8503/
```

Checked:

- top-level `系统监控` appears beside `首页 / 预测排名`, `AI 模拟盘`, and `AI Agent`
- `系统监控` renders title, disclaimer, total status, version linkages, alerts, layered metrics, history, and historical alerts
- `保存监控快照` writes one snapshot and active alerts to `data/agent_quant.db`
- history table appears after snapshot persistence
- no page `Traceback`, `Exception`, or `ModuleNotFoundError`
- quick navigation checks for `首页 / 预测排名`, `AI 模拟盘`, and `AI Agent` still pass without page errors

## Current Metrics From Local DB

Snapshot:

```text
snapshot_id: system_monitor_cht_20260701
overall_status: critical
trade_date: 2026-07-01
data_version: e05a630e526b6345
model_version: chronos_bolt_small
rag_index_version: 589e8e6e0e0786b2
run_id: agent_run_ae5accd3a693
portfolio_snapshot_id: paper_nav_cht_20260630
```

Selected metrics:

- data: `stock_coverage=0.9733`, `news_count=6590`, `full_text_ratio=0.0`, `feature_nan_ratio=0.0976`
- model: `prediction_nan_ratio=0.0`, `topk_stability=0.5385`, `rolling_icir=0.3414`
- RAG: `rag_query_count=135`, `rag_empty_rate=0.8296`, `source_trace_rate=1.0`, `dense_available=false`
- Agent: `agent_run_count=1`, `success_rate=1.0`, `failed_rate=0.0`
- portfolio: `position_source=latest_position_file`, `single_stock_concentration=0.1697`, `cash_ratio=0.0502`, `max_drawdown=-0.5030`

Active critical alerts:

- `data.full_text_ratio`: local news is still title-only, below threshold
- `rag.rag_empty_rate`: many RAG queries return no evidence
- `portfolio.max_drawdown`: current stored NAV drawdown breaches threshold

## Important Implementation Notes

- RAG monitoring does not instantiate or load the Dense embedding model on page render. It reads existing index metadata to keep the page responsive.
- Portfolio monitoring reads `outputs/portfolio/<user_id>/paper_positions_latest.csv` first. It only falls back to the generic `portfolio_position` table if the current paper-position file is missing.
- Industry concentration is left `null` when current positions do not contain industry data; it is not forced from blank industry fields.
- `collect_and_store_system_monitor_snapshot` only writes `system_monitor_snapshots` and `system_monitor_alerts`.

## Known Limits

- The local news database still has `full_text_ratio=0.0`; Phase 1 made this visible but upstream full-text coverage still needs real source data.
- Dense index file is currently missing for the local `outputs` snapshot, so `dense_available=false` in the monitor.
- `portfolio_snapshot_id` uses the latest NAV id when `paper_account_snapshot` has no row for the user.
- The first UI save wrote and then refreshed the same monitor snapshot in the development DB. It did not modify paper orders, positions, strategy, or Agent runtime behavior.

## Can Phase 3 Start?

Yes. Phase 2 acceptance criteria are met:

- five metric layers enter one snapshot
- alerts point to concrete layers and metrics
- same date, model, RAG index, Agent run, and portfolio snapshot can be linked
- monitoring is read-only with respect to business tables
- the page displays current status and historical snapshots

Next phase should start `agent/context/` and implement the lightweight ContextBuilder without modifying the four legacy Agent files.

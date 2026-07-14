# Phase 7 Handoff: Decision Attribution

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 7 adds a read-only decision attribution layer so a user can inspect how a saved recommendation and saved paper-trading decision were formed. It explains persisted results; it does not recompute ranking, RAG, AI adjustment, target weight, paper orders, or strategy output.

## Modified Files

- `portfolio/decision_attribution.py`: read-only attribution service for one stock.
- `portfolio/__init__.py`: exports the attribution entry points.
- `app/pages/ai_paper_trading.py`: adds a "单股决策归因" expander under the paper-trading page.
- `tests/unit/test_decision_attribution.py`: Phase 7 service and read-only safety tests.
- Documentation indexes updated in `README.md`, `PROJECT_STRUCTURE.md`, `PROJECT_FILE_DIRECTORY.md`, `docs/AGENT_USAGE.md`, and `docs/IMPROVEMENT_BASELINE.md`.

## Database Migration

No new migration was required.

The service only reads:

```text
outputs/users/<user_id>/recommendations/final_recommendations_*.json|csv
outputs/recommendations/final_recommendations_*.json|csv
outputs/portfolio/<user_id>/ai_paper_decisions_latest.json
outputs/portfolio/<user_id>/history/decisions/ai_paper_decisions_*.json
outputs/portfolio/<user_id>/paper_execution_diagnostics_latest.json
paper_decision_log, when db_path is provided and file fallback is missing
```

It never writes attribution results to files or SQLite.

## Source Priority

For recommendations, the service prefers user-specific results first:

```text
outputs/users/<user_id>/recommendations/
outputs/recommendations/
```

For paper decisions, the service prefers dated history when a trade date is provided, then falls back to latest, then SQLite:

```text
history/decisions/ai_paper_decisions_<date>.json
history/decisions/ai_paper_decisions_<date>_*.json
ai_paper_decisions_latest.json
paper_decision_log
```

## Attribution Fields

The payload includes:

- base allocation context: `original_target_weight`, `base_allocation_score`, `base_weight_note`
- model signal: original rank and score
- adjustment signal: news, user, effective news, combined adjustment, AI reliability
- clip check: expected effective adjustment, combined adjustment, and clipped position ratio
- final persisted results: recommendation target weight, paper target weight, action label, quantity, amount, fee
- lot and recursive allocation trace: matching `allocation_details`, `removed_candidates`, and `lot_execution_rounds`
- evidence trace: `evidence_news_ids`, `evidence_chunk_ids`, source reason
- uncertainty: missing source warnings and formula mismatch flags

Formula checks are labeled as `stored_formula_check`. They only verify whether persisted numeric fields match the existing formula; they are not used to regenerate final weights or trades.

## UI

The AI paper-trading page now includes:

```text
单股决策归因
```

The user selects a stock from the current paper decisions and can inspect:

- summary table
- markdown explanation
- raw attribution JSON
- warnings for missing sources

The UI reads the same persisted files as the service and does not call model, RAG, daily update, or paper-trading execution.

## Commands

Compilation:

```powershell
py -m compileall portfolio\decision_attribution.py app\pages\ai_paper_trading.py portfolio\__init__.py
```

Focused Phase 7 tests:

```powershell
py -m pytest tests\unit\test_decision_attribution.py -q
```

Paper-trading/explanation regression:

```powershell
py -m pytest tests\unit\test_decision_attribution.py tests\unit\test_scoring_explain.py tests\unit\test_daily_audit_log_contains_weight_rounds.py tests\unit\test_paper_trading_pipeline.py tests\unit\test_paper_trading_uses_original_and_ai_adjusted_signals.py -q
```

Full unit regression:

```powershell
py -m pytest tests\unit -q
```

## Test Results

- Compile Phase 7 modules: passed
- Focused Phase 7 tests: `4 passed`
- Paper-trading/explanation regression: `9 passed`
- Navigation/attribution regression after test update: `5 passed`
- Full unit regression: `541 passed`, `2 warnings`

## Page Verification

Verified against the local Streamlit app at:

```text
http://127.0.0.1:8503/
```

Checked:

- AI paper-trading page renders
- current paper-trading summary renders
- "单股决策归因" expander is available
- selecting a stock renders attribution summary and JSON
- no app `Traceback`, `ModuleNotFoundError`, or `NameError` was observed during the check

## Known Limits

- Latest execution diagnostics are stored as a latest-only file. For old trade dates, historical replay audit remains the authoritative daily audit source.
- Attribution explains the persisted output it can find. If recommendation, paper decision, or diagnostics are missing, it returns warnings instead of inventing a cause.
- The service does not yet expose a dedicated Agent tool; it is available as a Python service and Streamlit page section.

## Can Later Work Start?

Yes, for the scope requested in the roadmap through Phase 7. The roadmap marks later Multi-Agent, MCP/A2A, and Agentic RL work as "暂不立即实现"; those should remain gated until the listed prerequisites and data are available.

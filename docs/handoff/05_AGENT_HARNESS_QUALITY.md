# Phase 5 Handoff: Agent Harness Evidence, Answer, and Business Quality

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 5 extends the existing Agent Harness from process checks into quality checks. It keeps the existing harness and adds evidence quality, answer quality, and business-rule safety assertions.

This phase does not change Agent runtime behavior, trading strategy, paper-trading rules, RAG retrieval logic, confirmation/revalidation boundaries, or the four legacy Agent files.

## Modified Files

- `evaluation/agent_harness/schemas.py`: adds expected answer, evidence, and read-only business-safety fields.
- `evaluation/agent_harness/assertions.py`: adds `answer_quality`, `evidence_quality`, and `business_rule_safety` assertions.
- `evaluation/agent_harness/metrics.py`: adds quality rates and weighted `agent_composite_score`.
- `data/evaluation/agent_harness_cases.jsonl`: adds `agent_answer_quality_portfolio`.
- `tests/unit/test_agent_harness_quality.py`: synthetic quality assertion and composite metric tests.
- Documentation indexes updated in `README.md`, `PROJECT_STRUCTURE.md`, `PROJECT_FILE_DIRECTORY.md`, `docs/AGENT_USAGE.md`, and `docs/IMPROVEMENT_BASELINE.md`.

## Database Migration

No new migration was required.

The harness reads existing runtime, source, proposal, commit, and paper-order tables when evaluating safety. It does not write business state except through the existing harness cases that intentionally exercise preview/confirm paths.

## New Expected Fields

Answer quality:

```text
required_answer_phrases
forbidden_answer_phrases
required_answer_numbers
require_disclaimer
```

Evidence quality:

```text
required_evidence_ids
forbidden_evidence_ids
allowed_evidence_stock_codes
max_evidence_publish_time
```

Business safety:

```text
read_only_no_business_writes
```

`read_only_no_business_writes` checks that read-only cases do not create `action_proposals`, `action_commits`, or `paper_order` rows for the case user.

## Metrics

New metrics:

```text
source_quality_rate
answer_quality_rate
business_rule_pass_rate
agent_composite_score
```

Composite score weights:

```text
tool = 0.15
state = 0.15
source = 0.25
answer = 0.20
safety = 0.25
```

This satisfies the financial-scene requirement:

```text
source + safety = 0.50 > tool = 0.15
```

## Commands

Compilation:

```powershell
py -m compileall evaluation\agent_harness
```

Quality assertion tests:

```powershell
py -m pytest tests\unit\test_agent_harness_quality.py -q
```

Existing Harness runner regression:

```powershell
py -m pytest tests\unit\test_agent_harness_runner.py -q
```

Real Harness smoke for the new default quality case:

```powershell
python - <<'PY'
from evaluation.agent_harness.case_loader import load_cases
from evaluation.agent_harness.runner import run_harness
cases = [case for case in load_cases('data/evaluation/agent_harness_cases.jsonl') if case.case_id == 'agent_answer_quality_portfolio']
report = run_harness(cases, output_dir='runtime/phase5_harness_smoke', export=True)
print(report['metrics'])
print(report['report_path'])
PY
```

CLI check:

```powershell
py -m evaluation.agent_harness.cli --cases data\evaluation\agent_harness_cases.jsonl --output-dir runtime\phase5_cli --no-export
```

## Test Results

- Harness module compile: passed
- Harness quality tests: `4 passed in 2.94s`
- Existing Harness runner tests: `2 passed in 7.68s`
- New real Harness case: `case_pass_rate=1.0`, `agent_composite_score=1.0`
- Harness quality + runner + Agent safety regression: `8 passed in 21.78s`
- Agent wide regression: `100 passed in 77.76s`
- CLI check: exit code 0, `case_pass_rate=1.0`, `agent_composite_score=1.0`

## Page Verification

Verified in the in-app browser against:

```text
http://127.0.0.1:8503/
```

Checked:

- `AI Agent` control center renders
- quick questions render
- disclaimer renders
- no app `Traceback`, `ModuleNotFoundError`, or `NameError` was observed

Phase 5 only changes the offline harness/evaluation layer, so no Streamlit UI behavior was intentionally changed.

## What The Harness Can Now Detect

- answer missing required key phrase
- answer contains forbidden deterministic-return language
- answer omits required numbers
- answer omits the project disclaimer when required
- evidence references the wrong stock
- evidence comes after the allowed decision time
- required evidence id is missing
- forbidden evidence id is used
- read-only case creates proposals, commits, or paper orders

## Known Limits

- Claim-level source support is rule-based. It does not yet parse every natural-language claim into atomic facts.
- Evidence quality checks depend on available ids, stock codes, and publish times in tool outputs or runtime sources.
- The harness is still an offline evaluator. It does not block live Agent responses by itself.

## Can Phase 6 Start?

Yes. Phase 5 acceptance criteria are met:

- Harness no longer only checks flow
- evidence quality failures can be detected
- future evidence and wrong-stock evidence can be detected
- answer quality failures can be detected
- read-only business-rule violations can be detected
- composite score weights emphasize source quality and safety

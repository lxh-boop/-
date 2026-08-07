# V22.0.1 Worker Structured Output Recovery

## Scope

This is a focused repair on top of V22.0.0. The authoritative runtime remains:

`Canonical Intent -> all public Worker descriptions -> Worker calls -> upfront Worker DAG -> Worker-private Tool DAG -> SlotStore -> downstream Worker`

The MainAgent planning architecture is unchanged.

## Fixes

1. **W09 business JSON only**
   - W09 no longer asks the LLM to generate `completion_report`.
   - Runtime/contract code owns completion status and acceptance flow.
   - Claim/output limits are bounded to keep JSON safely inside the output budget.

2. **Evidence prompt deduplication**
   - When W01 publishes the same evidence payload into both `entity_external_evidence` and `evidence_source_records`, W09 receives the full evidence corpus only once.
   - The second slot keeps its slot identity and only carries a lightweight alias/metadata summary.

3. **Worker-local structural repair**
   - First W09 output is parsed and validated locally.
   - On incomplete/invalid JSON, one repair request receives only the invalid output, schema/error context, and already-authorized source task ids.
   - The repair request does **not** receive the original evidence corpus or original user task, so repair cannot become a second full analysis pass.
   - Thinking is disabled for these structured-output calls when the active `LLMService` supports that parameter.

4. **Slot publication gate**
   - `RunSlotStore.publish_worker_result()` publishes only when Worker status is completed/proposal-ready, completion is contract-satisfied, and a real materialized value exists in `data.slots`.
   - Failed, blocked, partial, or placeholder results cannot publish promised slots.
   - Coordinator emits `WORKER_SLOTS_PUBLISHED` only when at least one real slot was persisted.

5. **Recovery escalation semantics**
   - Worker-local recovery is exhausted before MainAgent sees an escalation.
   - A non-retryable structured-output failure preserves `worker_escalation_retryable=false`; MainAgent does not create a redundant same-shape replan.
   - A downstream Worker blocked only by a non-retryable upstream failure inherits `retryable=false`, so the blocked presentation node cannot indirectly restart the same failed chain.

6. **Tool DAG logging name**
   - Old `progressive_worker_tool_dag_*` operation labels are renamed to `worker_private_tool_dag_*` to match the actual upfront private Tool DAG behavior.

## Regression target

The real failure class from `agent_run_e41c41696534` is covered:

- primary W09 JSON is truncated;
- repair runs without raw evidence;
- valid repair completes W09 and allows downstream W06;
- failed repair publishes no W09/W06 slots and does not request a redundant MainAgent replan.

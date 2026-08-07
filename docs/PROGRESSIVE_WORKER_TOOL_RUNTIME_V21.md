# Progressive Worker / Tool Runtime V21.0.2

## Single authoritative runtime path

V21.0.2 keeps one execution path only:

`MainAgent CapabilityContract -> SlotBinder -> Runtime input gate -> selected Worker -> private Tool DAG -> published Slots -> Runtime contract validation -> ResultComposer`

There is no Router / GoalPlanning / IntentDecomposition / MultiTaskExecutor compatibility path and no WorkerResult-type fallback path.

## Worker visibility

MainAgent first receives summaries for all eligible Workers. After selecting a minimal candidate set it loads full public details only for those Workers. MainAgent explicitly chooses `worker_id`; Runtime validates the assignment but does not silently replace it.

## Tool visibility

A selected Worker sees only its private Tools whose declared required input Slots are currently available. It first receives Tool summaries, chooses candidate Tools, and only then loads full Tool schemas/details. MainAgent never receives private Tool details.

## Input authority

Input sufficiency is owned by Runtime and CapabilityContract.

- SlotBinder is the only source of Worker inputs.
- Runtime checks only contract-declared `required_inputs` before invoking a Worker.
- Empty containers are valid bound values; only an absent/`None` binding is missing.
- A Worker receives only contract-declared Slots actually bound to the task.
- A Worker must not infer that other Workers, Tools, data sources, or information domains exist.
- A Worker must not produce statements such as “an internal-model dimension was not covered” merely because that information was never assigned to the task.

W09 therefore analyzes only its supplied Slots. Unbound information is outside its world view, not a gap it is allowed to diagnose.

## Completion and local recovery

After a Tool batch, frozen successful outputs are compared deterministically with the Worker goal contract. If all required output keys are already satisfied, local Tool replan is skipped. An empty follow-up Tool DAG is therefore not allowed to turn a completed Worker into a failure.

## Replan audit

Replan audit distinguishes:

- `structural_progress`: the patch materially changes producers/bindings/repair structure.
- `execution_progress`: execution after the patch increases satisfied contracts.

These are separate from performance optimization, which is intentionally out of scope for V21.0.2.

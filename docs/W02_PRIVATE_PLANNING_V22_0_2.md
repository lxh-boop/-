# W02 Private Planning V22.0.2

## Goal

Preserve the V22 upfront Worker DAG while restoring real domain planning inside W02. MainAgent assigns a business objective; W02 decides its own private Tool DAG.

## Changes

- Removed the W02 entry-level GraphRef gate. Missing initial GraphRef is no longer automatically treated as user context missing.
- Added Worker-local reachable Tool discovery: a private Tool may become usable after another private Tool produces its required slot.
- Added `internal.entity.resolve_ranked_security`, private to W02, to turn structured ranking output into an authoritative Neo4j GraphRef without free-text guessing.
- W02 private planner can now plan chains such as `ranking -> entity resolution -> prediction` when the objective requires them. The sequence is not hard-coded by Runtime.
- Candidate validation requires the selected private Tools to form a reachable prerequisite chain.
- Worker-local bounded replan remains the first recovery layer before MainAgent escalation.

## Architectural invariants

1. MainAgent still sees Worker public descriptions only; it never sees W02 private Tool IDs or Tool DAGs.
2. MainAgent still creates the complete Worker DAG before execution.
3. W02 receives an objective and output contract, not a pre-scripted Tool sequence.
4. Entity identity discovered during W02 execution must be verified by the authoritative graph resolver.
5. W09 and W06 consume only published upstream Worker slots.

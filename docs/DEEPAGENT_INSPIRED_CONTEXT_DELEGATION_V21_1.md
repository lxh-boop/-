# DeepAgents-inspired Context & Delegation Runtime V21.1.0

## Runtime principles

- MainAgent sees all Worker delegation summaries first and selected Worker details only when needed.
- `delegation_description` is the primary semantic delegation surface; internal implementation IDs are hidden from MainAgent.
- Worker-to-Worker execution data uses RunSlotStore materialization, not coordinator/audit summaries.
- Each Worker sees only CapabilityContract-bound inputs.
- W09 performs generic structured synthesis over the inputs it actually receives and does not reason about unassigned information domains.
- W06 is presentation-only: structured terminal slots in, natural-language report out.
- Runtime owns provenance, completion metadata, slot references, and audit projections.
- Private Tool selection remains Worker-local and Tool availability is filtered by slot contracts.

## DeepAgents ideas adopted

1. Delegation descriptions as the parent-agent decision surface.
2. Progressive disclosure: summaries first, full details on demand.
3. Delegated context isolation: detailed working context stays in the delegated runtime; orchestration/audit context stays compact.
4. Clean structured return values between delegated workers instead of leaking internal tool histories.
5. Middleware-like runtime context projection before each Worker executes.

The runtime intentionally keeps the stricter MainAgent → Worker → private Tool boundary and CapabilityContract/Slot model rather than exposing arbitrary subagent/tool calls to MainAgent.

"""Pure helpers shared by domain Worker executors.

The helpers sanitize coordinator-visible values and extract GraphRefs from
upstream Worker results. This module performs no provider calls, graph writes,
task planning, or business-state mutations.
"""

from __future__ import annotations

from typing import Any

from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from

_BLOCKED_PUBLIC_KEYS = {
    "stock_code",
    "stock_codes",
    "stock_name",
    "ts_code",
    "symbol",
    "security_scope",
    "raw_payload",
    "raw_tool_payload",
    "tool_calls",
    "arguments",
    "sql",
    "cypher",
    "confirmation_token",
    "confirmation_token_hash",
    "api_key",
    "password",
    "secret",
    "private_chain_of_thought",
    "chain_of_thought",
    "reasoning_content",
}


def safe_public_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 5,
    max_items: int = 40,
) -> Any:
    # Scalar types stay typed even at the depth boundary. Converting ``False``
    # to the string ``"False"`` would later become truthy and could let an
    # unlocked identity overwrite a locked graph identity.
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= max_depth:
        return "<summarized>" if isinstance(value, (dict, list, tuple, set)) else str(value)[:1000]
    if isinstance(value, dict):
        return {
            str(key): safe_public_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
            )
            for key, item in list(value.items())[:max_items]
            if str(key).lower() not in _BLOCKED_PUBLIC_KEYS
        }
    if isinstance(value, (list, tuple, set)):
        return [
            safe_public_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
            )
            for item in list(value)[:max_items]
        ]
    if isinstance(value, str):
        return value[:3000] + ("…" if len(value) > 3000 else "")
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return safe_public_value(
            value.to_dict(),
            depth=depth,
            max_depth=max_depth,
            max_items=max_items,
        )
    return str(value)[:1000]


def execution_safe_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 14,
    max_items: int = 240,
) -> Any:
    """Preserve Worker-to-Worker business payloads without leaking blocked internals.

    Unlike ``safe_public_value`` this function is not an audit summarizer.  It is
    used at delegated Worker boundaries where concrete structured context must be
    retained.  This separation follows Deep Agents' context-isolation principle:
    execution context and observer-facing summaries are different projections.
    """

    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= max_depth:
        return str(value)[:12000] if not isinstance(value, (dict, list, tuple, set)) else "<execution-depth-limit>"
    if isinstance(value, dict):
        return {
            str(key): execution_safe_value(
                item, depth=depth + 1, max_depth=max_depth, max_items=max_items
            )
            for key, item in list(value.items())[:max_items]
            if str(key).lower() not in _BLOCKED_PUBLIC_KEYS
        }
    if isinstance(value, (list, tuple, set)):
        return [
            execution_safe_value(
                item, depth=depth + 1, max_depth=max_depth, max_items=max_items
            )
            for item in list(value)[:max_items]
        ]
    if isinstance(value, str):
        return value[:12000] + ("…" if len(value) > 12000 else "")
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return execution_safe_value(
            value.to_dict(), depth=depth, max_depth=max_depth, max_items=max_items
        )
    return str(value)[:4000]


def dependency_results(value: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in value.values() if isinstance(item, dict)]


def refs_from_dependencies(
    dependency_payloads: dict[str, dict[str, Any]],
    *,
    roles: set[str] | None = None,
    kinds: set[GraphNodeKind] | None = None,
) -> list[GraphRef]:
    refs: list[GraphRef] = []
    for payload in dependency_payloads.values():
        if not isinstance(payload, dict):
            continue
        candidates = []
        candidates.extend(payload.get("focus_refs") or [])
        candidates.extend(payload.get("evidence_refs") or [])
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        candidates.extend(metadata.get("produced_refs") or [])
        for ref in refs_from(candidates):
            if roles and ref.role not in roles:
                continue
            if kinds and ref.node_kind not in kinds:
                continue
            if not any(existing.node_id == ref.node_id and existing.role == ref.role for existing in refs):
                refs.append(ref)
    return refs


def contract_output_slots(task: Any) -> list[str]:
    result: list[str] = []
    for contract in getattr(task, "contracts", []) or []:
        row = contract if isinstance(contract, dict) else getattr(contract, "to_dict", lambda: {})()
        for output in row.get("promised_outputs") or []:
            if not isinstance(output, dict):
                continue
            slot = str(output.get("slot_id") or "").strip()
            if slot and slot not in result:
                result.append(slot)
    return result


def contract_input_slots(task: Any, *, required_only: bool = False) -> list[str]:
    result: list[str] = []
    for contract in getattr(task, "contracts", []) or []:
        row = contract if isinstance(contract, dict) else getattr(contract, "to_dict", lambda: {})()
        for item in row.get("required_inputs") or []:
            if not isinstance(item, dict):
                continue
            if required_only and not bool(item.get("required", True)):
                continue
            slot = str(item.get("slot_id") or "").strip()
            if slot and slot not in result:
                result.append(slot)
    return result


def contract_acceptance_rules(task: Any) -> list[str]:
    result: list[str] = []
    for contract in getattr(task, "contracts", []) or []:
        row = contract if isinstance(contract, dict) else getattr(contract, "to_dict", lambda: {})()
        for rule in row.get("acceptance_rule_ids") or []:
            value = str(rule).strip()
            if value and value not in result:
                result.append(value)
    return result

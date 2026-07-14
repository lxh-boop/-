from __future__ import annotations

from agent.context.schemas import ContextItem, extract_preserved_facts


ALWAYS_KEEP_SECTIONS = {
    "user_context",
    "portfolio_context",
    "business_constraints",
    "runtime_context",
    "tool_results",
    "evidence_context",
}


def _query_markers(query: str) -> set[str]:
    facts = extract_preserved_facts(query)
    markers: set[str] = set()
    for values in facts.values():
        markers.update(str(item) for item in values)
    for token in str(query or "").replace("，", " ").replace(",", " ").split():
        clean = token.strip().lower()
        if len(clean) >= 2:
            markers.add(clean)
    return markers


def _item_relevance(item: ContextItem, markers: set[str]) -> int:
    score = int(item.priority)
    if item.section in ALWAYS_KEEP_SECTIONS:
        score += 100
    text = item.text().lower()
    for marker in markers:
        if marker and marker.lower() in text:
            score += 8
    if item.source_ids:
        score += min(12, len(item.source_ids) * 2)
    return score


def select_context_items(
    items: list[ContextItem],
    query: str,
    *,
    max_history_items: int = 4,
    max_memory_items: int = 6,
) -> tuple[list[ContextItem], list[dict[str, str]]]:
    markers = _query_markers(query)
    selected: list[ContextItem] = []
    dropped: list[dict[str, str]] = []
    history_seen = 0
    memory_seen = 0

    ranked = sorted(
        items,
        key=lambda item: (_item_relevance(item, markers), item.priority),
        reverse=True,
    )
    for item in ranked:
        if item.section == "history_context":
            history_seen += 1
            if history_seen > max_history_items:
                dropped.append({"section": item.section, "title": item.title, "reason": "history_budget"})
                continue
        if item.section == "memory_context":
            memory_seen += 1
            if memory_seen > max_memory_items:
                dropped.append({"section": item.section, "title": item.title, "reason": "memory_budget"})
                continue
        selected.append(item)

    return selected, dropped

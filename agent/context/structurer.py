from __future__ import annotations

from agent.context.schemas import ContextItem, ContextSection


SECTION_ORDER = [
    "user_context",
    "portfolio_context",
    "market_context",
    "model_context",
    "evidence_context",
    "tool_results",
    "business_constraints",
    "open_questions",
    "runtime_context",
    "history_context",
    "memory_context",
]

SECTION_TITLES = {
    "user_context": "User Context",
    "portfolio_context": "Portfolio Context",
    "market_context": "Market Context",
    "model_context": "Model Context",
    "evidence_context": "Evidence Context",
    "tool_results": "Tool Results",
    "business_constraints": "Business Constraints",
    "open_questions": "Open Questions",
    "runtime_context": "Runtime Context",
    "history_context": "Conversation History",
    "memory_context": "Agent Memory",
}


def structure_context_items(items: list[ContextItem]) -> list[ContextSection]:
    grouped: dict[str, list[ContextItem]] = {}
    for item in items:
        grouped.setdefault(item.section, []).append(item)

    ordered_names = [name for name in SECTION_ORDER if name in grouped]
    ordered_names.extend(sorted(name for name in grouped if name not in SECTION_ORDER))
    sections: list[ContextSection] = []
    for name in ordered_names:
        section_items = sorted(grouped[name], key=lambda item: item.priority, reverse=True)
        sections.append(
            ContextSection(
                name=name,
                title=SECTION_TITLES.get(name, name.replace("_", " ").title()),
                items=section_items,
            )
        )
    return sections

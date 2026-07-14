from __future__ import annotations

import json
from typing import Any

from agent.context.schemas import ContextBudget, ContextSection, estimate_tokens, extract_preserved_facts


SECTION_BUDGET_ATTRS = {
    "user_context": "user_tokens",
    "portfolio_context": "portfolio_tokens",
    "history_context": "history_tokens",
    "memory_context": "history_tokens",
    "tool_results": "tools_tokens",
    "evidence_context": "rag_tokens",
    "business_constraints": "business_tokens",
    "runtime_context": "output_tokens",
}


def _merge_facts(left: dict[str, list[str]], right: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {key: list(values) for key, values in left.items()}
    for key, values in right.items():
        existing = set(merged.get(key, []))
        for value in values:
            if value not in existing:
                merged.setdefault(key, []).append(value)
                existing.add(value)
    return {key: values for key, values in merged.items() if values}


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _char_budget_for_tokens(max_tokens: int) -> int:
    return max(120, int(max_tokens * 2.6))


def compress_text_preserving_facts(value: Any, max_tokens: int) -> tuple[str, dict[str, list[str]], bool]:
    text = _stringify(value)
    facts = extract_preserved_facts(text)
    if estimate_tokens(text) <= max_tokens:
        return text, facts, False

    char_budget = _char_budget_for_tokens(max_tokens)
    fact_lines = []
    for key, values in facts.items():
        fact_lines.append(f"{key}: {', '.join(values[:40])}")
    fact_text = "\nPreserved facts: " + " | ".join(fact_lines) if fact_lines else ""
    head_budget = max(80, char_budget - len(fact_text) - 30)
    compressed = text[:head_budget].rstrip() + "\n...[compressed]" + fact_text
    while estimate_tokens(compressed) > max_tokens and head_budget > 40:
        head_budget = int(head_budget * 0.82)
        compressed = text[:head_budget].rstrip() + "\n...[compressed]" + fact_text
    if estimate_tokens(compressed) > max_tokens:
        compressed = compressed[:_char_budget_for_tokens(max_tokens)].rstrip()
    return compressed, facts, True


def _section_budget(section_name: str, budget: ContextBudget) -> int:
    attr = SECTION_BUDGET_ATTRS.get(section_name)
    if attr:
        return int(getattr(budget, attr))
    return max(120, int(budget.output_tokens))


def compress_sections(
    sections: list[ContextSection],
    budget: ContextBudget,
) -> tuple[str, int, dict[str, list[str]], list[dict[str, str]], list[str]]:
    parts: list[str] = []
    preserved: dict[str, list[str]] = {}
    dropped: list[dict[str, str]] = []
    warnings: list[str] = []

    for section in sections:
        section_tokens = _section_budget(section.name, budget)
        remaining = section_tokens
        section_lines = [f"## {section.title}"]
        for item in section.items:
            item_budget = max(80, min(remaining, section_tokens // max(1, len(section.items)) + 80))
            if item_budget <= 40:
                dropped.append({"section": section.name, "title": item.title, "reason": "section_token_budget"})
                continue
            text, facts, was_compressed = compress_text_preserving_facts(item.content, item_budget)
            preserved = _merge_facts(preserved, facts)
            if was_compressed:
                warnings.append(f"compressed:{section.name}:{item.title}")
            item_block = f"- {item.title}: {text}"
            section_lines.append(item_block)
            remaining -= estimate_tokens(item_block)
        if len(section_lines) > 1:
            parts.append("\n".join(section_lines))

    compressed_text = "\n\n".join(parts).strip()
    while estimate_tokens(compressed_text) > budget.max_total_tokens and parts:
        removed = parts.pop()
        dropped.append({"section": "tail", "title": removed.splitlines()[0].replace("#", "").strip(), "reason": "total_token_budget"})
        compressed_text = "\n\n".join(parts).strip()
    token_estimate = estimate_tokens(compressed_text)
    if token_estimate > budget.max_total_tokens:
        warnings.append("context_exceeds_budget_after_compression")
        compressed_text = compressed_text[:_char_budget_for_tokens(budget.max_total_tokens)].rstrip()
        token_estimate = estimate_tokens(compressed_text)
    return compressed_text, token_estimate, preserved, dropped, warnings

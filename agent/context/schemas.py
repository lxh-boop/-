from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


STOCK_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
DATE_RE = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
SOURCE_ID_RE = re.compile(
    r"\b(?:src|chunk|news|retrieval|run|agent_run|plan|decision|snapshot|paper_nav|order|position)_[A-Za-z0-9_\-]+\b"
)


def estimate_tokens(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, int(ascii_count / 4) + int(non_ascii_count / 2))


def extract_preserved_facts(value: Any) -> dict[str, list[str]]:
    text = str(value or "")
    facts = {
        "stock_codes": sorted(set(STOCK_CODE_RE.findall(text))),
        "dates": sorted(set(DATE_RE.findall(text))),
        "numbers": sorted(set(NUMBER_RE.findall(text)))[:80],
        "source_ids": sorted(set(SOURCE_ID_RE.findall(text))),
    }
    return {key: items for key, items in facts.items() if items}


@dataclass(frozen=True)
class ContextBudget:
    max_total_tokens: int = 1800
    user_tokens: int = 220
    history_tokens: int = 260
    tools_tokens: int = 420
    rag_tokens: int = 360
    portfolio_tokens: int = 280
    business_tokens: int = 180
    output_tokens: int = 260

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class ContextItem:
    section: str
    title: str
    content: Any
    priority: int = 50
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return str(self.content if self.content is not None else "")

    def token_estimate(self) -> int:
        return estimate_tokens(self.text())

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "title": self.title,
            "content": self.content,
            "priority": self.priority,
            "source_ids": list(self.source_ids),
            "metadata": dict(self.metadata),
            "token_estimate": self.token_estimate(),
        }


@dataclass
class ContextSection:
    name: str
    title: str
    items: list[ContextItem] = field(default_factory=list)

    def token_estimate(self) -> int:
        return sum(item.token_estimate() for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "items": [item.to_dict() for item in self.items],
            "token_estimate": self.token_estimate(),
        }


@dataclass
class BuiltAgentContext:
    user_id: str
    run_id: str
    query: str
    phase: str
    sections: list[ContextSection]
    compressed_text: str
    token_estimate: int
    token_budget: ContextBudget
    preserved_facts: dict[str, list[str]] = field(default_factory=dict)
    dropped_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "run_id": self.run_id,
            "query": self.query,
            "phase": self.phase,
            "sections": [section.to_dict() for section in self.sections],
            "compressed_text": self.compressed_text,
            "token_estimate": self.token_estimate,
            "token_budget": self.token_budget.to_dict(),
            "preserved_facts": dict(self.preserved_facts),
            "dropped_items": list(self.dropped_items),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.context.compressor import compress_sections
from agent.context.gatherer import gather_context_items
from agent.context.schemas import BuiltAgentContext, ContextBudget
from agent.context.selector import select_context_items
from agent.context.structurer import structure_context_items


def build_agent_context(
    *,
    query: str,
    user_id: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    session_id: str = "",
    run_id: str = "",
    phase: str = "pre_execution",
    tool_result: dict[str, Any] | None = None,
    orchestration: dict[str, Any] | None = None,
    decomposition: dict[str, Any] | None = None,
    agent_role: str = "supervisor",
    budget: ContextBudget | None = None,
) -> BuiltAgentContext:
    budget = budget or ContextBudget()
    items, gather_warnings = gather_context_items(
        query=query,
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
        session_id=session_id,
        run_id=run_id,
        tool_result=tool_result,
        orchestration=orchestration,
        decomposition=decomposition,
        agent_role=agent_role,
    )
    selected, selection_dropped = select_context_items(items, query)
    sections = structure_context_items(selected)
    compressed_text, token_estimate, preserved_facts, compression_dropped, compression_warnings = compress_sections(
        sections,
        budget,
    )
    return BuiltAgentContext(
        user_id=user_id,
        run_id=run_id,
        query=str(query or ""),
        phase=phase,
        sections=sections,
        compressed_text=compressed_text,
        token_estimate=token_estimate,
        token_budget=budget,
        preserved_facts=preserved_facts,
        dropped_items=[*selection_dropped, *compression_dropped],
        warnings=[*gather_warnings, *compression_warnings],
        metadata={
            "phase": phase,
            "item_count": len(items),
            "selected_item_count": len(selected),
            "section_count": len(sections),
            "has_tool_result": tool_result is not None,
            "has_orchestration": orchestration is not None,
        },
    )

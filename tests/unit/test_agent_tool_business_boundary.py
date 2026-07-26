"""Hard boundary tests for business functions and Agent-only tools."""

from __future__ import annotations

from scripts.verify_agent_tool_boundaries import verify


def test_non_write_business_and_agent_tool_layers_are_one_way() -> None:
    result = verify()
    assert result["success"] is True, result["errors"]

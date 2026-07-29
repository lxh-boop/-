"""Shared contracts, registry, validation, and execution for Agent tools.

Concrete business tools live outside this package.  The runtime only describes,
authorizes, validates, executes, and audits registered capabilities.
"""

from .contracts import (
    AGENT_MAIN,
    AGENT_READ,
    AGENT_WORKER,
    AGENT_WRITE,
    OP_PROPOSAL,
    OP_READ,
    OP_SYSTEM,
    OP_WRITE,
    TOOL_RESULT_SCHEMA_VERSION,
    TOOL_VISIBILITY_PUBLIC,
    TOOL_VISIBILITY_SYSTEM_PRIVATE,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    UnifiedToolResult,
)
from .executor import ToolExecutor
from .registry import ToolRegistry
from .validation import (
    description,
    normalise_raw_result,
    result_schema,
    safe_argument_keys,
    schema,
    validate_input,
    validate_output,
)

__all__ = [
    "AGENT_MAIN",
    "AGENT_READ",
    "AGENT_WORKER",
    "AGENT_WRITE",
    "OP_PROPOSAL",
    "OP_READ",
    "OP_SYSTEM",
    "OP_WRITE",
    "TOOL_RESULT_SCHEMA_VERSION",
    "TOOL_VISIBILITY_PUBLIC",
    "TOOL_VISIBILITY_SYSTEM_PRIVATE",
    "TOOL_VISIBILITY_WORKER_PRIVATE",
    "ToolDefinition",
    "ToolExecutor",
    "ToolRegistry",
    "UnifiedToolResult",
    "description",
    "normalise_raw_result",
    "result_schema",
    "safe_argument_keys",
    "schema",
    "validate_input",
    "validate_output",
]

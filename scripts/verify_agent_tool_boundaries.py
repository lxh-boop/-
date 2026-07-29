"""Verify the non-write business/function and Agent-tool dependency boundary."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BUSINESS_ROOTS = (
    PROJECT_ROOT / "application" / "use_cases",
)

BUSINESS_CONTRACT_FILES = (
    PROJECT_ROOT / "application" / "contracts.py",
)

READ_SERVICE_FILES = (
    "agent/services/evidence_service.py",
    "agent/services/market_analysis_service.py",
    "agent/services/mcp_readonly_client.py",
    "agent/services/portfolio_risk_service.py",
    "agent/services/portfolio_service.py",
    "agent/services/python_sandbox_service.py",
    "agent/services/system_auxiliary_service.py",
    "agent/services/user_profile_service.py",
)

THIN_AGENT_TOOL_FILES = (
    "agent/memory/memory_tool.py",
    "agent/tools/evidence_adapters.py",
    "agent/tools/market_analysis_adapters.py",
    "agent/tools/portfolio_comparison_adapters.py",
    "agent/tools/portfolio_recommendation_tools.py",
    "agent/tools/portfolio_risk_adapters.py",
    "agent/tools/portfolio_state_adapters.py",
    "agent/tools/strategy_read_tools.py",
    "agent/tools/system_auxiliary_adapters.py",
)

REMOVED_NON_WRITE_COMPATIBILITY_FILES = (
    "agent/tools/tool_registry.py",
    "agent/tools/portfolio_risk_tool.py",
    "agent/tools/portfolio_state_tool.py",
    "agent/tools/position_recommendation_tool.py",
    "agent/tools/python_sandbox_tool.py",
    "agent/tools/ranking_tool.py",
    "agent/tools/replacement_recommendation_tool.py",
    "agent/tools/report_tool.py",
    "agent/tools/scheduler_tool.py",
    "agent/tools/stock_analysis_tool.py",
    "agent/tools/stock_lookup_tool.py",
    "agent/tools/stock_news_tool.py",
    "agent/tools/stock_rag_tool.py",
    "agent/tools/user_profile_tool.py",
)

FORBIDDEN_TOOL_DIRECT_IMPORT_PREFIXES = (
    "database",
    "pipelines",
    "portfolio",
    "rag",
    "scheduler",
)

FORBIDDEN_BUSINESS_TOOL_MARKERS = (
    "ToolDefinition",
    "ToolPermission",
    "ToolResult",
    "confirmation_token",
    "permission_scope",
    "tool_name",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append(str(node.module or ""))
    return result


def verify() -> dict:
    errors: list[str] = []

    for root in BUSINESS_ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for module in _imports(path):
                if module == "agent.tools" or module.startswith(
                    "agent.tools."
                ):
                    errors.append(
                        f"business_imports_agent_tool:{path.relative_to(PROJECT_ROOT)}:{module}"
                    )
            for marker in FORBIDDEN_BUSINESS_TOOL_MARKERS:
                if marker in source:
                    errors.append(
                        f"business_contains_agent_tool_contract:{path.relative_to(PROJECT_ROOT)}:{marker}"
                    )

    for path in BUSINESS_CONTRACT_FILES:
        source = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_BUSINESS_TOOL_MARKERS:
            if marker in source:
                errors.append(
                    f"business_contract_contains_agent_tool_field:{path.relative_to(PROJECT_ROOT)}:{marker}"
                )

    for relative in READ_SERVICE_FILES:
        path = PROJECT_ROOT / relative
        for module in _imports(path):
            if module == "agent.tools" or module.startswith(
                "agent.tools."
            ):
                errors.append(
                    f"read_service_imports_agent_tool:{relative}:{module}"
                )

    for relative in THIN_AGENT_TOOL_FILES:
        path = PROJECT_ROOT / relative
        if not path.exists():
            errors.append(f"agent_tool_missing:{relative}")
            continue
        source = path.read_text(encoding="utf-8")
        imports = _imports(path)
        for module in imports:
            if module.startswith(FORBIDDEN_TOOL_DIRECT_IMPORT_PREFIXES):
                errors.append(
                    f"agent_tool_bypasses_business_layer:{relative}:{module}"
                )
        if "execute_" not in source or "_tool(" not in source:
            errors.append(f"agent_tool_name_not_explicit:{relative}")

    for relative in REMOVED_NON_WRITE_COMPATIBILITY_FILES:
        if (PROJECT_ROOT / relative).exists():
            errors.append(f"removed_compatibility_file_returned:{relative}")

    removed_mixed_modules = (
        PROJECT_ROOT / "agent" / "tools" / "_common.py",
        PROJECT_ROOT / "agent" / "tools" / "portfolio_comparison_tools.py",
    )
    for path in removed_mixed_modules:
        if path.exists():
            errors.append(
                f"mixed_tool_module_still_exists:{path.relative_to(PROJECT_ROOT)}"
            )

    from agent.tool_engine import build_core_tool_definitions

    registered_non_write_count = 0
    required_description_sections = (
        "Function:",
        "Applies when:",
        "Not for:",
        "Preconditions:",
        "Main inputs:",
        "Main outputs:",
        "Side effects:",
    )
    for definition in build_core_tool_definitions():
        if definition.operation_type not in {"read", "system"}:
            continue
        registered_non_write_count += 1
        handler = definition.execution_handler
        handler_module = str(getattr(handler, "__module__", "") or "")
        handler_name = str(getattr(handler, "__name__", "") or "")
        if not (
            handler_module.startswith("agent.tools.")
            or handler_module == "agent.memory.memory_tool"
        ):
            errors.append(
                f"registered_non_write_bypasses_agent_tool:{definition.name}:{handler_module}"
            )
        if not (
            handler_name.startswith("execute_")
            and handler_name.endswith("_tool")
        ):
            errors.append(
                f"registered_non_write_name_not_explicit:{definition.name}:{handler_name}"
            )
        for section in required_description_sections:
            if section not in str(definition.description or ""):
                errors.append(
                    f"registered_non_write_description_incomplete:{definition.name}:{section}"
                )
        if definition.requires_approval:
            errors.append(
                f"registered_non_write_requires_approval:{definition.name}"
            )

    payload = {
        "success": not errors,
        "business_roots": [
            str(path.relative_to(PROJECT_ROOT)) for path in BUSINESS_ROOTS
        ],
        "checked_read_services": len(READ_SERVICE_FILES),
        "checked_agent_tool_adapters": len(THIN_AGENT_TOOL_FILES),
        "checked_removed_compatibility_files": len(
            REMOVED_NON_WRITE_COMPATIBILITY_FILES
        ),
        "checked_registered_non_write_tools": registered_non_write_count,
        "errors": errors,
    }
    return payload


if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys


FORBIDDEN_PUBLIC_FIELDS = {"stock_code", "stock_codes", "stock_name", "ts_code", "security_scope"}
PUBLIC_CONTRACT_FILES = {
    Path("agent/graph/contracts.py"),
    Path("agent/collaboration/models.py"),
}
FORBIDDEN_TEST_MODULE_PREFIXES = {
    "agent.collaboration_v2",
    "agent.event_impact_agent",
    "agent.handoff",
    "agent.intent_classifier",
    "agent.orchestration",
    "agent.portfolio_qa_agent",
    "agent.specialists",
}
FORBIDDEN_LEGACY_DIRECTORIES = {
    Path("agent/collaboration_v2"),
    Path("agent/handoff"),
    Path("agent/orchestration"),
    Path("agent/specialists"),
}
FORBIDDEN_TEST_IMPORT_NAMES = {
    ("agent.router", "route_agent_query"),
    ("agent.executor", "_execute_readonly_multi_agent_collaboration"),
    ("agent.executor", "_feature_unavailable_result"),
    ("agent.executor", "_normalise_readonly_multi_agent_tasks"),
}


def _dataclass_fields(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields: set[str] = set()
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields.add(item.target.id)
        if fields:
            result[node.name] = fields
    return result


def _stale_test_imports(root: Path) -> list[str]:
    errors: list[str] = []
    tests_root = root / "tests"
    if not tests_root.exists():
        return errors
    for path in tests_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == prefix
                        or alias.name.startswith(prefix + ".")
                        for prefix in FORBIDDEN_TEST_MODULE_PREFIXES
                    ):
                        errors.append(
                            f"stale_test_import:{relative}:{alias.name}"
                        )
            if not isinstance(node, ast.ImportFrom):
                continue
            module = str(node.module or "")
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in FORBIDDEN_TEST_MODULE_PREFIXES
            ):
                errors.append(f"stale_test_import:{relative}:{module}")
            for alias in node.names:
                if (module, alias.name) in FORBIDDEN_TEST_IMPORT_NAMES:
                    errors.append(
                        f"stale_test_import:{relative}:{module}.{alias.name}"
                    )
    return errors


def _legacy_source_imports(root: Path) -> list[str]:
    errors: list[str] = []
    for relative_root in (
        Path("agent"),
        Path("application"),
        Path("benchmarks"),
        Path("evaluation"),
    ):
        source_root = root / relative_root
        if not source_root.exists():
            continue
        for path in source_root.rglob("*.py"):
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
            relative = path.relative_to(root).as_posix()
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(str(node.module or ""))
                for module in modules:
                    if any(
                        module == prefix
                        or module.startswith(prefix + ".")
                        for prefix in {
                            "agent.handoff",
                            "agent.orchestration",
                            "agent.specialists",
                        }
                    ):
                        errors.append(
                            f"legacy_source_import:{relative}:{module}"
                        )
    return errors


def _worker_boundary_errors(root: Path) -> list[str]:
    errors: list[str] = []
    workers = root / "agent" / "collaboration" / "workers"
    if workers.exists():
        for path in workers.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(root).as_posix()
            for marker in (
                "GraphProviderAdapter",
                "GraphImpactService",
                "execute_tool_legacy_dict",
                "provider.",
            ):
                if marker in text:
                    errors.append(
                        f"worker_bypasses_private_tool_runtime:{relative}:{marker}"
                    )
    worker_tools = root / "agent" / "worker_tools"
    if worker_tools.exists():
        for path in worker_tools.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "agent.collaboration.agent_directory" in text:
                errors.append(
                    "worker_tool_depends_on_worker_identity:"
                    + path.relative_to(root).as_posix()
                )
            for marker in ("GraphProviderAdapter", "GraphImpactService"):
                if marker in text:
                    errors.append(
                        "worker_tool_depends_on_composite_provider:"
                        + path.relative_to(root).as_posix()
                        + f":{marker}"
                    )
    specialist = root / "agent" / "collaboration" / "specialist_runtime.py"
    if specialist.exists():
        text = specialist.read_text(encoding="utf-8")
        if "if task.assigned_agent" in text or "elif task.assigned_agent" in text:
            errors.append("specialist_runtime_dispatches_by_worker_name")
        for marker in ("GraphProviderAdapter", "GraphImpactService"):
            if marker in text:
                errors.append(
                    f"specialist_runtime_depends_on_provider:{marker}"
                )
    validator = root / "agent" / "worker_planning" / "validator.py"
    if not validator.exists() or "DagValidator" not in validator.read_text(
        encoding="utf-8"
    ):
        errors.append("worker_plan_shared_dag_validator_missing")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--check-neo4j", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    errors: list[str] = []

    for relative in FORBIDDEN_LEGACY_DIRECTORIES:
        directory = root / relative
        if directory.exists() and any(directory.glob("*.py")):
            errors.append(
                f"legacy_directory_present:{relative.as_posix()}"
            )
    errors.extend(_stale_test_imports(root))
    errors.extend(_legacy_source_imports(root))
    errors.extend(_worker_boundary_errors(root))
    for rel in PUBLIC_CONTRACT_FILES:
        path = root / rel
        if not path.exists():
            errors.append(f"missing_contract_file:{rel.as_posix()}")
            continue
        for cls, fields in _dataclass_fields(path).items():
            blocked = sorted(fields & FORBIDDEN_PUBLIC_FIELDS)
            if blocked:
                errors.append(f"forbidden_public_fields:{rel.as_posix()}:{cls}:{','.join(blocked)}")

    executor = root / "agent/executor.py"
    if executor.exists():
        text = executor.read_text(encoding="utf-8")
        if "agent.collaboration_v2" in text or '"agent_collaboration_v2"' in text:
            errors.append("legacy_executor_entry_present")
        if "financial_graph_agent" not in text:
            errors.append("financial_graph_entry_missing")

    tool_engine = root / "agent/tool_engine.py"
    if (
        tool_engine.exists()
        and "execute_tool_legacy_dict"
        in tool_engine.read_text(encoding="utf-8")
    ):
        errors.append("legacy_tool_dict_executor_present")

    for relative in (
        Path("agent/graph/provider_adapter.py"),
        Path("agent/graph/providers/evidence.py"),
        Path("agent/graph/providers/portfolio.py"),
    ):
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in (
            "def retrieve_evidence(",
            "def load_portfolio_snapshot(",
        ):
            if marker in text:
                errors.append(
                    "composite_provider_operation_present:"
                    f"{relative.as_posix()}:{marker}"
                )

    requirements = root / "requirements.txt"
    if requirements.exists() and "neo4j" not in requirements.read_text(encoding="utf-8").lower():
        errors.append("neo4j_dependency_missing")

    pipeline = root / "pipelines/paper_trading_pipeline.py"
    if pipeline.exists():
        pipeline_text = pipeline.read_text(encoding="utf-8")
        if "sync_portfolio_payload" not in pipeline_text:
            errors.append("portfolio_graph_sync_missing")

    neo4j_status = "not_checked"
    if args.check_neo4j and not errors:
        try:
            root_text = str(root)
            if root_text not in sys.path:
                sys.path.insert(0, root_text)
            from agent.graph.bootstrap import FinancialGraphBootstrapper
            service = FinancialGraphBootstrapper.from_env()
            try:
                service.store.verify_connectivity()
                neo4j_status = "ok"
            finally:
                service.store.close()
        except Exception as exc:
            neo4j_status = f"failed:{type(exc).__name__}:{exc}"
            errors.append(neo4j_status)

    payload = {
        "success": not errors,
        "project_root": str(root),
        "neo4j": neo4j_status,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()

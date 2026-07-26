from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


FORBIDDEN_PUBLIC_FIELDS = {"stock_code", "stock_codes", "stock_name", "ts_code", "security_scope"}
PUBLIC_CONTRACT_FILES = {
    Path("agent/graph/contracts.py"),
    Path("agent/collaboration/models.py"),
}
FORBIDDEN_TEST_MODULE_PREFIXES = {
    "agent.collaboration_v2",
    "agent.event_impact_agent",
    "agent.intent_classifier",
    "agent.portfolio_qa_agent",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--check-neo4j", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    errors: list[str] = []

    if (root / "agent/collaboration_v2").exists():
        errors.append("legacy_directory_present:agent/collaboration_v2")
    errors.extend(_stale_test_imports(root))
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

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Any


BANNED_IMPORT_ROOTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "requests",
    "httpx",
    "shutil",
    "ctypes",
    "pickle",
    "importlib",
}

DEFAULT_ALLOWED_IMPORT_ROOTS = {
    "math",
    "statistics",
    "numpy",
    "pandas",
    "strategies",
}

BANNED_CALLS = {
    "__import__",
    "eval",
    "exec",
    "open",
    "compile",
    "input",
}


@dataclass(frozen=True)
class StrategySecurityScan:
    passed: bool
    code_hash: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "code_hash": self.code_hash,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def code_hash(source: str) -> str:
    return hashlib.sha256(str(source or "").encode("utf-8")).hexdigest()


def _import_root(name: str) -> str:
    return str(name or "").split(".", 1)[0]


def scan_strategy_source(
    source: str,
    *,
    allowed_import_roots: set[str] | None = None,
) -> StrategySecurityScan:
    allowed = set(allowed_import_roots or DEFAULT_ALLOWED_IMPORT_ROOTS)
    errors: list[str] = []
    warnings: list[str] = []
    digest = code_hash(source)

    try:
        tree = ast.parse(str(source or ""))
    except SyntaxError as exc:
        return StrategySecurityScan(
            passed=False,
            code_hash=digest,
            errors=[f"syntax_error:{exc.msg}"],
        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [str(node.module or "")]
            for name in names:
                root = _import_root(name)
                if root in BANNED_IMPORT_ROOTS:
                    errors.append(f"banned_import:{root}")
                elif root and root not in allowed:
                    errors.append(f"import_not_allowed:{root}")

        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id in BANNED_CALLS:
                errors.append(f"banned_call:{target.id}")
            if isinstance(target, ast.Attribute):
                root = target.value
                if isinstance(root, ast.Name) and root.id in BANNED_IMPORT_ROOTS:
                    errors.append(f"banned_attribute_call:{root.id}.{target.attr}")

        if isinstance(node, ast.Name) and node.id in BANNED_IMPORT_ROOTS:
            warnings.append(f"banned_name_reference:{node.id}")

    return StrategySecurityScan(
        passed=not errors,
        code_hash=digest,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
    )

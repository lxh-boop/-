from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


TARGET_SYMBOLS = {
    "run_agent_request",
    "route_agent_query",
    "decompose_intent",
    "decompose_with_llm",
    "observe_goal_completion",
    "assess_completion_with_llm",
    "generate_report_with_llm",
    "critique_report_with_llm",
    "resolve_active_llm_settings",
    "register_llm_execution_dependencies",
    "get_llm_execution_dependencies",
    "LLMService",
}

DYNAMIC_TARGETS = [
    ("agent.executor", "run_agent_request"),
    ("agent.router", "route_agent_query"),
    ("agent.intent_decomposition", "decompose_intent"),
    ("agent.intent_decomposition.llm_decomposer", "decompose_with_llm"),
    ("agent.intent_decomposition.llm_decomposer", "assess_completion_with_llm"),
    ("agent.intent_decomposition.llm_decomposer", "generate_report_with_llm"),
    ("agent.intent_decomposition.llm_decomposer", "critique_report_with_llm"),
    ("agent.goal_planning", "observe_goal_completion"),
    ("core.llm.service", "LLMService"),
    ("core.llm.runtime_settings", "resolve_active_llm_settings"),
]

IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "outputs",
    "data",
    "models",
    "logs",
    "dist",
    "build",
}

OLD_LLM_FIELDS = {
    "llm_api_key",
    "llm_base_url",
    "llm_model",
}

SENSITIVE_CONTEXT_FIELDS = {
    "api_key",
    "llm_api_key",
    "password",
    "secret",
    "authorization",
    "token",
    "tushare_token",
}


@dataclass
class Definition:
    module: str
    file: str
    line: int
    qualified_name: str
    accepted_keywords: list[str]
    required_keywords: list[str]
    has_var_keyword: bool
    signature_text: str


@dataclass
class CallSite:
    module: str
    file: str
    line: int
    display_name: str
    resolved_name: str
    keywords: list[str]
    has_star_kwargs: bool


@dataclass
class Finding:
    severity: str
    code: str
    file: str
    line: int
    message: str


def should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in IGNORED_DIR_NAMES:
            return True
        if part.startswith("_backup"):
            return True
        if part.startswith("context_audit_bundle"):
            return True
    return False


def module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], list[str], bool, str]:
    args = node.args
    positional = [a.arg for a in [*args.posonlyargs, *args.args]]
    kwonly = [a.arg for a in args.kwonlyargs]
    accepted = positional + kwonly

    required: list[str] = []
    positional_required_count = len(positional) - len(args.defaults)
    required.extend(positional[:positional_required_count])
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is None:
            required.append(arg.arg)

    fragments = list(positional)
    if args.vararg:
        fragments.append(f"*{args.vararg.arg}")
    elif kwonly:
        fragments.append("*")
    fragments.extend(kwonly)
    if args.kwarg:
        fragments.append(f"**{args.kwarg.arg}")
    return accepted, required, args.kwarg is not None, f"({', '.join(fragments)})"


def call_display_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        cur: ast.expr = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
    return "<dynamic>"


def top_level_definitions(tree: ast.AST, module: str, file: str) -> dict[str, Definition]:
    result: dict[str, Definition] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            accepted, required, has_varkw, signature = format_signature(node)
            result[node.name] = Definition(
                module=module,
                file=file,
                line=node.lineno,
                qualified_name=f"{module}.{node.name}" if module else node.name,
                accepted_keywords=accepted,
                required_keywords=required,
                has_var_keyword=has_varkw,
                signature_text=signature,
            )
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    accepted, required, has_varkw, signature = format_signature(child)
                    qn = f"{module}.{node.name}.{child.name}" if module else f"{node.name}.{child.name}"
                    result[f"{node.name}.{child.name}"] = Definition(
                        module=module,
                        file=file,
                        line=child.lineno,
                        qualified_name=qn,
                        accepted_keywords=accepted,
                        required_keywords=required,
                        has_var_keyword=has_varkw,
                        signature_text=signature,
                    )
    return result


def collect_imports(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    symbols: dict[str, str] = {}
    modules: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                symbols[local] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                modules[local] = alias.name
    return symbols, modules


def resolve_call_name(
    display: str,
    module: str,
    local_defs: dict[str, Definition],
    imported_symbols: dict[str, str],
    imported_modules: dict[str, str],
) -> str:
    if "." not in display:
        if display in local_defs:
            return local_defs[display].qualified_name
        return imported_symbols.get(display, display)

    first, rest = display.split(".", 1)
    if first in imported_modules:
        return f"{imported_modules[first]}.{rest}"
    if first in imported_symbols:
        return f"{imported_symbols[first]}.{rest}"
    return display


def add_textual_findings(path: Path, root: Path, text: str, findings: list[Finding]) -> None:
    rel = str(path.relative_to(root))
    rel_norm = rel.replace("\\", "/")
    lines = text.splitlines()

    allowed_resolve = {
        "core/llm/runtime_settings.py",
        "agent/executor.py",
        "app.py",
        "local_config.py",
    }
    allowed_legacy_client = {
        "llm_client.py",
        "core/llm/service.py",
        "core/llm/adapters/openai_compatible.py",
        "core/llm/adapters/ollama.py",
    }

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()

        if "route_agent_query(" in line and any(f"{name}=" in line for name in OLD_LLM_FIELDS):
            findings.append(Finding(
                "HIGH", "ROUTER_OLD_LLM_KEYWORD", rel, index,
                "route_agent_query 调用仍直接传递旧 LLM 参数。"
            ))

        if "run_agent_request(" in line and "profile_id=" in line:
            findings.append(Finding(
                "HIGH", "EXECUTOR_UNSUPPORTED_PROFILE_ID", rel, index,
                "run_agent_request 调用仍传递 profile_id；需与真实签名核对。"
            ))

        if "resolve_active_llm_settings(" in line and rel_norm not in allowed_resolve and "/tests/" not in f"/{rel_norm}":
            findings.append(Finding(
                "MEDIUM", "DOWNSTREAM_RESOLVES_LLM_SETTINGS", rel, index,
                "下游模块自行解析活动模型配置，可能破坏单次运行固定 Profile。"
            ))

        if "LLMClient(" in line and rel_norm not in allowed_legacy_client and "/tests/" not in f"/{rel_norm}":
            findings.append(Finding(
                "MEDIUM", "DIRECT_LEGACY_LLMCLIENT", rel, index,
                "业务/Agent 模块仍直接构造 LLMClient，统一 LLMService 迁移可能未完成。"
            ))

        if "load_local_config" in line and rel_norm.startswith("agent/"):
            findings.append(Finding(
                "MEDIUM", "AGENT_READS_LOCAL_CONFIG", rel, index,
                "Agent 下游模块直接读取 local_config，可能在运行中重新选择模型。"
            ))

        if rel_norm.startswith("agent/") and any(re.search(rf"['\"]{re.escape(key)}['\"]\s*:", line) for key in SENSITIVE_CONTEXT_FIELDS):
            findings.append(Finding(
                "HIGH", "SENSITIVE_FIELD_IN_AGENT_PAYLOAD", rel, index,
                "Agent 可序列化字典/Context 中出现敏感字段名，需确认不会进入日志、消息、记忆或 Artifact。"
            ))

        if rel_norm.startswith("agent/") and any(re.search(rf"\b{re.escape(key)}\s*=", line) for key in OLD_LLM_FIELDS):
            if rel_norm not in {"agent/executor.py"} and "/tests/" not in f"/{rel_norm}":
                findings.append(Finding(
                    "LOW", "LEGACY_LLM_ARGUMENT_REMAINS", rel, index,
                    "Agent 下游仍保留旧 llm_api_key/base_url/model 参数。"
                ))


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}", file=sys.stderr)
        return 2

    output_dir = root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = output_dir / f"agent_llm_chain_audit_{stamp}.md"
    json_path = output_dir / f"agent_llm_chain_audit_{stamp}.json"

    parsed: dict[str, dict[str, Any]] = {}
    parse_errors: list[dict[str, Any]] = []
    all_definitions: dict[str, Definition] = {}
    short_name_definitions: dict[str, list[Definition]] = {}
    findings: list[Finding] = []
    call_sites: list[CallSite] = []

    python_files = [
        path for path in root.rglob("*.py")
        if not should_skip(path, root)
    ]

    for path in python_files:
        rel = str(path.relative_to(root))
        mod = module_name(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            parse_errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue

        add_textual_findings(path, root, text, findings)

        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            parse_errors.append({
                "file": rel,
                "line": exc.lineno,
                "error": f"SyntaxError: {exc.msg}",
            })
            continue

        defs = top_level_definitions(tree, mod, rel)
        imported_symbols, imported_modules = collect_imports(tree)
        parsed[mod] = {
            "file": rel,
            "tree": tree,
            "definitions": defs,
            "imported_symbols": imported_symbols,
            "imported_modules": imported_modules,
        }
        for definition in defs.values():
            all_definitions[definition.qualified_name] = definition
            short = definition.qualified_name.rsplit(".", 1)[-1]
            short_name_definitions.setdefault(short, []).append(definition)

    for mod, info in parsed.items():
        tree = info["tree"]
        defs = info["definitions"]
        imported_symbols = info["imported_symbols"]
        imported_modules = info["imported_modules"]
        file = info["file"]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            display = call_display_name(node.func)
            resolved = resolve_call_name(display, mod, defs, imported_symbols, imported_modules)
            keywords = [kw.arg for kw in node.keywords if kw.arg is not None]
            has_star_kwargs = any(kw.arg is None for kw in node.keywords)
            call = CallSite(
                module=mod,
                file=file,
                line=node.lineno,
                display_name=display,
                resolved_name=resolved,
                keywords=keywords,
                has_star_kwargs=has_star_kwargs,
            )
            call_sites.append(call)

            target = all_definitions.get(resolved)
            if target is None and "." not in resolved:
                candidates = short_name_definitions.get(resolved, [])
                if len(candidates) == 1:
                    target = candidates[0]

            if target is not None and not target.has_var_keyword and not has_star_kwargs:
                unexpected = sorted(set(keywords) - set(target.accepted_keywords))
                if unexpected:
                    findings.append(Finding(
                        "HIGH",
                        "UNEXPECTED_KEYWORD_ARGUMENT",
                        file,
                        node.lineno,
                        f"{display} -> {target.qualified_name} 不接受关键字参数：{', '.join(unexpected)}；"
                        f"目标签名 {target.signature_text}",
                    ))

            if display.endswith("route_agent_query"):
                old = sorted(set(keywords) & (OLD_LLM_FIELDS | {"llm_settings"}))
                if old:
                    findings.append(Finding(
                        "HIGH",
                        "ROUTE_AGENT_QUERY_LEGACY_PROTOCOL",
                        file,
                        node.lineno,
                        f"route_agent_query 仍传递旧协议参数：{', '.join(old)}。",
                    ))

            if display.endswith("run_agent_request") and "profile_id" in keywords:
                findings.append(Finding(
                    "HIGH",
                    "RUN_AGENT_REQUEST_PROFILE_ID",
                    file,
                    node.lineno,
                    "run_agent_request 调用传入 profile_id，需与入口签名统一。",
                ))

    # Dynamic signatures from the actual interpreter/runtime.
    dynamic_results: list[dict[str, Any]] = []
    original_sys_path = list(sys.path)
    sys.path.insert(0, str(root))
    try:
        for module_name_text, attr_name in DYNAMIC_TARGETS:
            try:
                module = importlib.import_module(module_name_text)
                obj = getattr(module, attr_name)
                dynamic_results.append({
                    "module": module_name_text,
                    "attribute": attr_name,
                    "file": inspect.getsourcefile(obj) or getattr(module, "__file__", ""),
                    "signature": str(inspect.signature(obj)),
                    "status": "ok",
                })
            except Exception as exc:
                dynamic_results.append({
                    "module": module_name_text,
                    "attribute": attr_name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
    finally:
        sys.path[:] = original_sys_path

    target_defs = sorted(
        [
            asdict(definition)
            for definition in all_definitions.values()
            if definition.qualified_name.rsplit(".", 1)[-1] in TARGET_SYMBOLS
            or definition.qualified_name.endswith(".LLMService")
        ],
        key=lambda item: (item["qualified_name"], item["file"], item["line"]),
    )
    target_calls = sorted(
        [
            asdict(call)
            for call in call_sites
            if call.display_name.rsplit(".", 1)[-1] in TARGET_SYMBOLS
        ],
        key=lambda item: (item["display_name"], item["file"], item["line"]),
    )

    # Deduplicate findings.
    unique: dict[tuple[str, str, str, int, str], Finding] = {}
    for finding in findings:
        key = (
            finding.severity,
            finding.code,
            finding.file,
            finding.line,
            finding.message,
        )
        unique[key] = finding
    findings = sorted(
        unique.values(),
        key=lambda item: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(item.severity, 9),
            item.file,
            item.line,
            item.code,
        ),
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(root),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "scanned_python_files": len(python_files),
        "parsed_modules": len(parsed),
        "parse_errors": parse_errors,
        "dynamic_signatures": dynamic_results,
        "target_definitions": target_defs,
        "target_calls": target_calls,
        "findings": [asdict(item) for item in findings],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    severity_counts = {
        level: sum(1 for item in findings if item.severity == level)
        for level in ("HIGH", "MEDIUM", "LOW")
    }

    md: list[str] = []
    md.append("# Agent / LLM 全链路接口审计")
    md.append("")
    md.append(f"- 生成时间：`{payload['generated_at']}`")
    md.append(f"- 项目目录：`{root}`")
    md.append(f"- Python：`{sys.executable}`")
    md.append(f"- 扫描 Python 文件：`{len(python_files)}`")
    md.append(f"- 成功解析模块：`{len(parsed)}`")
    md.append(
        f"- 发现：HIGH `{severity_counts['HIGH']}` / "
        f"MEDIUM `{severity_counts['MEDIUM']}` / LOW `{severity_counts['LOW']}`"
    )
    md.append("")

    md.append("## 1. 高可信接口错误")
    md.append("")
    high = [item for item in findings if item.severity == "HIGH"]
    if not high:
        md.append("未发现可由静态分析直接确认的高可信关键字参数错误。")
    else:
        md.append("| 文件 | 行 | 代码 | 问题 |")
        md.append("|---|---:|---|---|")
        for item in high:
            message = item.message.replace("|", "\\|").replace("\n", " ")
            md.append(f"| `{item.file}` | {item.line} | `{item.code}` | {message} |")
    md.append("")

    md.append("## 2. 架构迁移残留")
    md.append("")
    rest = [item for item in findings if item.severity != "HIGH"]
    if not rest:
        md.append("未发现中低优先级迁移残留。")
    else:
        md.append("| 级别 | 文件 | 行 | 代码 | 问题 |")
        md.append("|---|---|---:|---|---|")
        for item in rest:
            message = item.message.replace("|", "\\|").replace("\n", " ")
            md.append(
                f"| {item.severity} | `{item.file}` | {item.line} | "
                f"`{item.code}` | {message} |"
            )
    md.append("")

    md.append("## 3. 运行时真实签名")
    md.append("")
    md.append("| 模块 | 对象 | 状态 | 文件/错误 | 签名 |")
    md.append("|---|---|---|---|---|")
    for item in dynamic_results:
        detail = item.get("file") or item.get("error") or ""
        md.append(
            f"| `{item['module']}` | `{item['attribute']}` | `{item['status']}` | "
            f"`{str(detail).replace('|', '\\|')}` | "
            f"`{str(item.get('signature') or '').replace('|', '\\|')}` |"
        )
    md.append("")

    md.append("## 4. 目标函数定义")
    md.append("")
    md.append("| 函数 | 文件 | 行 | 签名 |")
    md.append("|---|---|---:|---|")
    for item in target_defs:
        md.append(
            f"| `{item['qualified_name']}` | `{item['file']}` | {item['line']} | "
            f"`{item['signature_text']}` |"
        )
    md.append("")

    md.append("## 5. 目标函数调用点")
    md.append("")
    md.append("| 调用 | 解析目标 | 文件 | 行 | 关键字参数 |")
    md.append("|---|---|---|---:|---|")
    for item in target_calls:
        md.append(
            f"| `{item['display_name']}` | `{item['resolved_name']}` | "
            f"`{item['file']}` | {item['line']} | "
            f"`{', '.join(item['keywords'])}` |"
        )
    md.append("")

    md.append("## 6. 解析或导入失败")
    md.append("")
    if not parse_errors and all(item["status"] == "ok" for item in dynamic_results):
        md.append("无。")
    else:
        for item in parse_errors:
            md.append(f"- `{item.get('file')}`：{item.get('error')}")
        for item in dynamic_results:
            if item["status"] != "ok":
                md.append(
                    f"- `{item['module']}.{item['attribute']}`：{item.get('error')}"
                )
    md.append("")
    md.append("## 7. 说明")
    md.append("")
    md.append(
        "- 本脚本只读取项目代码并生成报告，不修改任何项目文件。"
    )
    md.append(
        "- HIGH 中的 `UNEXPECTED_KEYWORD_ARGUMENT` 属于可直接导致 "
        "`TypeError: unexpected keyword argument` 的高可信问题。"
    )
    md.append(
        "- 动态导入失败不一定代表业务代码错误，也可能由启动环境、可选依赖或配置副作用导致。"
    )

    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"审计完成：{md_path}")
    print(f"JSON 明细：{json_path}")
    print(
        f"HIGH={severity_counts['HIGH']} "
        f"MEDIUM={severity_counts['MEDIUM']} "
        f"LOW={severity_counts['LOW']}"
    )
    return 1 if severity_counts["HIGH"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

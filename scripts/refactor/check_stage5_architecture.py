from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    ROOT / "Dockerfile.compose",
    ROOT / "docker-compose.yml",
    ROOT / "requirements-compose-api.txt",
    ROOT / "requirements-compose-streamlit.txt",
    ROOT / "compose.env.example",
    ROOT / "scripts/docker/start_compose.ps1",
    ROOT / "scripts/docker/stop_compose.ps1",
    ROOT / "scripts/docker/logs_compose.ps1",
    ROOT / "scripts/docker/test_compose.ps1",
    ROOT / "scripts/refactor/stage5_browser_acceptance.py",
]

REQUIRED_MOUNTS = {
    "./data:/app/data",
    "./models:/app/models",
    "./outputs:/app/outputs",
    "./logs:/app/logs",
    "./runtime:/app/runtime",
    "./local_app_config.json:/app/local_app_config.json",
}

PROTECTED_DOCKERIGNORE_MARKERS = {
    ".venv/",
    "data/",
    "models/",
    "outputs/",
    "logs/",
    "runtime/",
    ".env",
    "local_app_config.json",
    ".streamlit/secrets.toml",
}

SENSITIVE_LITERAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|password)\s*:\s*[\"']?[^${\s][^\s]{7,}"),
)


def normalized_compose_mounts(text: str) -> set[str]:
    rows: set[str] = set()
    source = ""
    target = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("source:"):
            source = stripped.split(":", 1)[1].strip().strip('"\'')
        elif stripped.startswith("target:"):
            target = stripped.split(":", 1)[1].strip().strip('"\'')
            if source and target:
                rows.add(f"{source}:{target}")
                source = ""
                target = ""
    return rows


def main() -> int:
    violations: list[dict[str, Any]] = []

    for path in REQUIRED_FILES:
        if not path.exists():
            violations.append({"file": str(path.relative_to(ROOT)), "issue": "missing_stage5_file"})

    compose_path = ROOT / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
    dockerfile_path = ROOT / "Dockerfile.compose"
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8") if dockerfile_path.exists() else ""
    ignore_path = ROOT / ".dockerignore"
    ignore_text = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""

    for service in ("api:", "streamlit:"):
        if service not in compose_text:
            violations.append({"file": "docker-compose.yml", "issue": "missing_service", "service": service[:-1]})

    for marker in (
        "target: api",
        "target: streamlit",
        "condition: service_healthy",
        "STOCK_AGENT_API_URL: http://api:8010",
        "STOCK_AGENT_TASK_DB: /app/runtime/task_runtime.sqlite3",
        "host.docker.internal:host-gateway",
        "restart: unless-stopped",
        "init: true",
    ):
        if marker not in compose_text:
            violations.append({"file": "docker-compose.yml", "issue": "compose_marker_missing", "marker": marker})

    mounts = normalized_compose_mounts(compose_text)
    missing_mounts = sorted(REQUIRED_MOUNTS - mounts)
    if missing_mounts:
        violations.append({"file": "docker-compose.yml", "issue": "persistent_mounts_missing", "mounts": missing_mounts})

    if "source: .\n" in compose_text or "- .:/app" in compose_text or "- .:/app/" in compose_text:
        violations.append({"file": "docker-compose.yml", "issue": "source_tree_bind_mount_not_allowed"})

    for pattern in SENSITIVE_LITERAL_PATTERNS:
        match = pattern.search(compose_text)
        if match:
            violations.append({"file": "docker-compose.yml", "issue": "possible_sensitive_literal", "match": match.group(0)[:80]})

    for marker in ("AS api", "AS streamlit", "COPY . /app"):
        if marker not in dockerfile_text:
            violations.append({"file": "Dockerfile.compose", "issue": "dockerfile_marker_missing", "marker": marker})

    for forbidden in ("COPY local_app_config.json", "COPY .env", "COPY data", "COPY models", "COPY runtime"):
        if forbidden in dockerfile_text:
            violations.append({"file": "Dockerfile.compose", "issue": "protected_content_copied", "marker": forbidden})

    missing_ignore = sorted(marker for marker in PROTECTED_DOCKERIGNORE_MARKERS if marker not in ignore_text)
    if missing_ignore:
        violations.append({"file": ".dockerignore", "issue": "protected_ignore_missing", "markers": missing_ignore})


    legacy_dockerfile = ROOT / "Dockerfile.agent-api"
    if legacy_dockerfile.exists():
        violations.append({"file": "Dockerfile.agent-api", "issue": "legacy_container_entry_remains"})

    api_requirements = (ROOT / "requirements-compose-api.txt").read_text(encoding="utf-8") if (ROOT / "requirements-compose-api.txt").exists() else ""
    frontend_requirements = (ROOT / "requirements-compose-streamlit.txt").read_text(encoding="utf-8") if (ROOT / "requirements-compose-streamlit.txt").exists() else ""
    for dep in ("fastapi", "uvicorn", "pydantic", "neo4j", "sentence-transformers"):
        if dep not in api_requirements.lower():
            violations.append({"file": "requirements-compose-api.txt", "issue": "api_dependency_missing", "dependency": dep})
    for dep in ("streamlit", "pandas", "plotly", "requests"):
        if dep not in frontend_requirements.lower():
            violations.append({"file": "requirements-compose-streamlit.txt", "issue": "frontend_dependency_missing", "dependency": dep})
    if "torch" in frontend_requirements.lower() or "transformers" in frontend_requirements.lower():
        violations.append({"file": "requirements-compose-streamlit.txt", "issue": "backend_dependency_in_frontend_image"})

    main_text = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
    if 'version="4.0.0"' not in main_text or '"deployment_mode"' not in main_text:
        violations.append({"file": "server/api/main.py", "issue": "stage5_health_metadata_missing"})

    profile_text = (ROOT / "core/llm/profiles.py").read_text(encoding="utf-8")
    if "STOCK_LOCAL_LLM_BASE_URL" not in profile_text:
        violations.append({"file": "core/llm/profiles.py", "issue": "docker_host_llm_override_missing"})

    config_text = (ROOT / "config.py").read_text(encoding="utf-8")
    for marker in ("os.environ.get(\"QLIB_PROVIDER_URI\"", "DFT_UNET_CHECKPOINT_PATH"):
        if marker not in config_text:
            violations.append({"file": "config.py", "issue": "container_path_override_missing", "marker": marker})

    payload = {
        "stage": 5,
        "violation_count": len(violations),
        "required_files": [str(path.relative_to(ROOT)) for path in REQUIRED_FILES],
        "compose_mounts": sorted(mounts),
        "violations": violations,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())

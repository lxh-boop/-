from __future__ import annotations

import os
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent


def _reload_directories() -> list[str]:
    """Return only source-code directories that should trigger API reloads.

    Runtime databases, logs, generated Markdown, model files and data folders are
    intentionally outside this list. Watching the whole ``/app`` bind mount can
    make WatchFiles subscribe to ``/app/runtime`` and fail with an OS-level I/O
    watcher error on Docker Desktop for Windows.
    """

    candidates = (
        "agent",
        "server",
        "core",
        "application",
        "database",
        "pipelines",
        "scoring",
        "portfolio",
        "rag",
        "skills",
    )
    return [
        str(path)
        for name in candidates
        if (path := PROJECT_ROOT / name).is_dir()
    ]


def main() -> None:
    reload_dirs = _reload_directories()
    if not reload_dirs:
        raise RuntimeError(
            f"No API source directories were found under {PROJECT_ROOT}."
        )

    uvicorn.run(
        "server.api.main:app",
        host=os.environ.get("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENT_API_PORT", "8010")),
        reload=True,
        reload_dirs=reload_dirs,
        reload_includes=["*.py"],
        access_log=True,
    )


if __name__ == "__main__":
    main()

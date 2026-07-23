from __future__ import annotations

import uvicorn

from .config import AgentApiSettings


def main() -> None:
    settings = AgentApiSettings.from_env()
    uvicorn.run(
        "agent.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()

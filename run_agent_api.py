from __future__ import annotations

import os
import uvicorn


def main() -> None:
    uvicorn.run(
        "server.api.main:app",
        host=os.environ.get("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENT_API_PORT", "8010")),
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()

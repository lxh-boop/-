# Stage 5 Docker Compose deployment

The Compose deployment runs two services:

```text
Streamlit -> HTTP/SSE -> FastAPI -> Task Runtime / Worker -> Application Service
```

Persistent project directories are bind-mounted from the host and are never
copied into Docker images:

```text
data
models
outputs
logs
runtime
external_repos
local_app_config.json
```

Use the one-click scripts installed under `D:\google` for build, start, stop,
logs, and Chrome acceptance testing.

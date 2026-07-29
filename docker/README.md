# Stage 6.5 production Docker Compose deployment

The production stack contains two services:

```text
Browser -> React/Nginx -> HTTP/SSE -> FastAPI -> Task Runtime / Agent / Application Service
```

Services:

- `frontend`: React production build served by Nginx on host port `3000`;
- `api`: FastAPI and Task Runtime on host port `8010`.

Streamlit and the legacy Python HTTP client were removed at Stage 6.5. Persistent host directories remain bind-mounted and are never copied into images:

```text
data
models
outputs
logs
runtime
external_repos
local_app_config.json
```

Use the scripts installed under `D:\google` for build/start, stop, logs and Chrome acceptance testing.

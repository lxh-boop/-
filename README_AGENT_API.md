# Stock Daily App API — Stage 4

Stage 4 keeps the frontend-independent boundary introduced in Stage 3 and adds a durable long-task runtime.

## Runtime architecture

```text
Streamlit / future React
        ↓ HTTP + SSE
FastAPI
        ↓
Application Service
        ↓
Agent / RAG / Portfolio / Pipeline / Repository
```

Long-running work uses a separate process per task:

```text
POST task → task_id → Worker process → SQLite task state/events
                       ↓
             cancel / timeout / retry
```

## Task endpoints

```text
POST /api/v1/tasks
GET  /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/cancel
POST /api/v1/tasks/{task_id}/acknowledge
GET  /api/v1/tasks/{task_id}/events   # text/event-stream
```

Supported business task types:

- `agent.run`
- `dashboard.rolling_update`
- `dashboard.backtest`
- `paper-trading.update`
- `paper-profile.ai-news-adjustment`
- `paper-profile.scheduler-manual`

Diagnostic task types are used only by the Stage 4 acceptance workflow.

## Persistence and recovery

Task state and event history are stored in:

```text
runtime/task_runtime.sqlite3
```

The file contains task metadata, status, progress, results and error summaries. LLM credentials are **not** persisted in this database. A credential required by an Agent Worker is passed through that process's environment and removed immediately after startup.

When FastAPI restarts, unfinished `queued`, `running` or `cancelling` records are marked `interrupted`. The client can display the explicit terminal state and allow the user to submit a new task.

## Cancellation and timeout

Each long task runs in an independent process group. Cancellation and timeout terminate the Worker process tree, including nested update subprocesses. This avoids leaving a Python thread running after the UI reports cancellation.

## Environment variables

```text
AGENT_API_HOST=127.0.0.1
AGENT_API_PORT=8010
STOCK_AGENT_API_URL=http://127.0.0.1:8010
STOCK_AGENT_API_TIMEOUT_SECONDS=600
STOCK_AGENT_TASK_DB=D:\stock_daily_app\runtime\task_runtime.sqlite3
STOCK_AGENT_MAX_CONCURRENT_TASKS=4
```

No real password, Token or API key belongs in this document.

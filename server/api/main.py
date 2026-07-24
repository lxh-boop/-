from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.contracts import OperationResponse
from server.api.dispatch import (
    agent_bootstrap,
    dashboard_bootstrap,
    invoke_agent,
    invoke_dashboard,
    invoke_handoff,
    invoke_model,
    invoke_monitor,
    invoke_paper,
    invoke_paper_profile,
    invoke_reflection,
    model_bootstrap,
    paper_bootstrap,
)
from server.api.router_factory import build_operation_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stock Daily App API",
        version="3.0.0",
        description="Frontend-independent HTTP boundary for Streamlit and future React clients.",
    )
    origins = [item.strip() for item in os.environ.get("STOCK_AGENT_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health", response_model=OperationResponse)
    def health() -> OperationResponse:
        return OperationResponse(
            success=True,
            data={
                "status": "ok",
                "service": "stock-daily-app-api",
                "version": "3.0.0",
                "project_root": str(Path.cwd()),
            },
        )

    app.include_router(build_operation_router(prefix="/api/v1/dashboard", tag="dashboard", invoker=invoke_dashboard, bootstrap=dashboard_bootstrap))
    app.include_router(build_operation_router(prefix="/api/v1/agent", tag="agent", invoker=invoke_agent, bootstrap=agent_bootstrap))
    app.include_router(build_operation_router(prefix="/api/v1/paper-trading", tag="paper-trading", invoker=invoke_paper, bootstrap=paper_bootstrap))
    app.include_router(build_operation_router(prefix="/api/v1/paper-profile", tag="paper-profile", invoker=invoke_paper_profile))
    app.include_router(build_operation_router(prefix="/api/v1/model-search", tag="model-search", invoker=invoke_model, bootstrap=model_bootstrap))
    app.include_router(build_operation_router(prefix="/api/v1/system-monitor", tag="system-monitor", invoker=invoke_monitor))
    app.include_router(build_operation_router(prefix="/api/v1/handoff", tag="handoff", invoker=invoke_handoff))
    app.include_router(build_operation_router(prefix="/api/v1/reflection", tag="reflection", invoker=invoke_reflection))
    return app


app = create_app()

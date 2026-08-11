from __future__ import annotations

import os
from contextlib import asynccontextmanager
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
from server.api.tasks import router as tasks_router, task_manager
from server.api.routers.web_dashboard import router as web_dashboard_router
from server.api.routers.web_stocks import router as web_stocks_router
from server.api.routers.web_models import router as web_models_router
from server.api.routers.web_backtests import router as web_backtests_router
from server.api.routers.web_news import router as web_news_router
from server.api.routers.web_settings import router as web_settings_router
from server.api.routers.web_monitor import router as web_monitor_router
from server.api.routers.web_paper_trading import router as web_paper_trading_router
from server.api.routers.web_agent import router as web_agent_router
from scheduler.runtime_scheduler import shutdown_runtime_scheduler, start_runtime_scheduler


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Task recovery belongs to the real API process lifecycle, not TaskManager
    # construction. Compose enables it explicitly so imports/tests cannot
    # accidentally interrupt live production tasks.
    if os.environ.get("STOCK_AGENT_RECOVER_INTERRUPTED_ON_START", "0") == "1":
        task_manager.recover_on_api_startup()
    # 正式 API 进程即常驻调度器宿主；测试环境由 runtime_scheduler 自动禁用。
    start_runtime_scheduler()
    try:
        yield
    finally:
        shutdown_runtime_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stock Daily App API",
        version="4.0.0",
        description="React + FastAPI boundary with persistent daily scheduler.",
        lifespan=_lifespan,
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
                "version": "4.0.0",
                "deployment_mode": os.environ.get("STOCK_APP_DEPLOYMENT_MODE", "local"),
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
    app.include_router(tasks_router)
    app.include_router(web_dashboard_router)
    app.include_router(web_stocks_router)
    app.include_router(web_models_router)
    app.include_router(web_backtests_router)
    app.include_router(web_news_router)
    app.include_router(web_settings_router)
    app.include_router(web_monitor_router)
    app.include_router(web_paper_trading_router)
    app.include_router(web_agent_router)
    return app


app = create_app()

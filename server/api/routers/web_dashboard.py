from __future__ import annotations

from fastapi import APIRouter, Query
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.dashboard import present_freshness, present_ranking_page, present_summary
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/dashboard", tags=["web-dashboard"])

@router.get("/summary", response_model=OperationResponse)
def summary() -> OperationResponse:
    return web_call(lambda: present_summary(web_read_service.dashboard_summary()))

@router.get("/rankings", response_model=OperationResponse)
def rankings(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> OperationResponse:
    return web_call(lambda: present_ranking_page(web_read_service.ranking_page(offset=offset, limit=limit)))

@router.get("/model-status", response_model=OperationResponse)
def model_status() -> OperationResponse:
    return web_call(lambda: present_summary({"metrics": web_read_service.metrics(), "selected_strategy": web_read_service.selected_strategy(), "settings": web_read_service.public_settings()}))

@router.get("/data-freshness", response_model=OperationResponse)
def data_freshness() -> OperationResponse:
    return web_call(lambda: present_freshness(web_read_service.data_freshness()))

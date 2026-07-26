from __future__ import annotations

from fastapi import APIRouter
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.models import present_catalog, present_metrics, present_search_results
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/models", tags=["web-models"])

@router.get("/metrics", response_model=OperationResponse)
def metrics() -> OperationResponse:
    return web_call(lambda: present_metrics(web_read_service.metrics(), web_read_service.selected_strategy()))

@router.get("/catalog", response_model=OperationResponse)
def catalog() -> OperationResponse:
    return web_call(lambda: present_catalog(web_read_service.model_catalog()))

@router.get("/search-results", response_model=OperationResponse)
def search_results() -> OperationResponse:
    return web_call(lambda: present_search_results(web_read_service.model_search_results()))

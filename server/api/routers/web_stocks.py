from __future__ import annotations

from fastapi import APIRouter, Query
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.stocks import present_detail, present_evidence, present_explanation, present_history
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/stocks", tags=["web-stocks"])

@router.get("/{stock_code}", response_model=OperationResponse)
def detail(stock_code: str) -> OperationResponse:
    return web_call(lambda: present_detail(web_read_service.stock_detail(stock_code)))

@router.get("/{stock_code}/history", response_model=OperationResponse)
def history(stock_code: str, limit: int = Query(120, ge=1, le=1000)) -> OperationResponse:
    return web_call(lambda: present_history(web_read_service.stock_history(stock_code, limit=limit)))

@router.get("/{stock_code}/evidence", response_model=OperationResponse)
def evidence(stock_code: str, query: str = "", top_k: int = Query(10, ge=1, le=50)) -> OperationResponse:
    return web_call(lambda: present_evidence(web_read_service.stock_evidence(stock_code, query=query, top_k=top_k)))

@router.get("/{stock_code}/explanation", response_model=OperationResponse)
def explanation(stock_code: str) -> OperationResponse:
    return web_call(lambda: present_explanation(web_read_service.stock_explanation(stock_code)))

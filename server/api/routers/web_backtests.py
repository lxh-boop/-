from __future__ import annotations

from fastapi import APIRouter, HTTPException
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.backtests import present_detail, present_equity, present_list, present_predictions, present_trades
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/backtests", tags=["web-backtests"])

def _bundle(backtest_id: str = "latest"):
    if backtest_id != "latest":
        raise HTTPException(status_code=404, detail="阶段 6.2 仅暴露当前只读回测结果")
    return web_read_service.backtest_bundle()

@router.get("", response_model=OperationResponse)
def list_backtests() -> OperationResponse:
    return web_call(lambda: present_list(_bundle()))

@router.get("/{backtest_id}", response_model=OperationResponse)
def detail(backtest_id: str) -> OperationResponse:
    return web_call(lambda: present_detail(_bundle(backtest_id)))

@router.get("/{backtest_id}/equity", response_model=OperationResponse)
def equity(backtest_id: str) -> OperationResponse:
    return web_call(lambda: present_equity(_bundle(backtest_id)))

@router.get("/{backtest_id}/trades", response_model=OperationResponse)
def trades(backtest_id: str) -> OperationResponse:
    return web_call(lambda: present_trades(_bundle(backtest_id)))

@router.get("/{backtest_id}/predictions", response_model=OperationResponse)
def predictions(backtest_id: str) -> OperationResponse:
    return web_call(lambda: present_predictions(_bundle(backtest_id)))

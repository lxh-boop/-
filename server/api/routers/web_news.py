from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.news import present_event, present_events
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/news", tags=["web-news"])

@router.get("/events", response_model=OperationResponse)
def events(stock_code: str | None = None, event_type: str | None = None, start_date: str | None = None, end_date: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> OperationResponse:
    return web_call(lambda: present_events(web_read_service.news_events(stock_code=stock_code, event_type=event_type, start_date=start_date, end_date=end_date, offset=offset, limit=limit)))

@router.get("/events/{event_id}", response_model=OperationResponse)
def event(event_id: str) -> OperationResponse:
    def load():
        value = web_read_service.news_event(event_id)
        if value is None:
            raise HTTPException(status_code=404, detail="未找到新闻事件")
        return present_event(value)
    return web_call(load)

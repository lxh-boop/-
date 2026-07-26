from __future__ import annotations

from fastapi import APIRouter
from application.web_read_service import web_read_service
from server.api.contracts import OperationResponse
from server.api.presenters.settings import present_settings
from server.api.routers.web_common import web_call

router = APIRouter(prefix="/api/v1/web/settings", tags=["web-settings"])

@router.get("", response_model=OperationResponse)
def settings() -> OperationResponse:
    return web_call(lambda: present_settings(web_read_service.public_settings()))

from __future__ import annotations

import uuid
from typing import Any, Callable
from fastapi import HTTPException

from server.api.contracts import OperationResponse


def web_ok(data: Any) -> OperationResponse:
    return OperationResponse(success=True, data=data, request_id=uuid.uuid4().hex)


def web_call(callable_obj: Callable[[], Any]) -> OperationResponse:
    request_id = uuid.uuid4().hex
    try:
        return OperationResponse(success=True, data=callable_obj(), request_id=request_id)
    except HTTPException:
        raise
    except Exception as exc:
        return OperationResponse(
            success=False,
            data=None,
            error={
                "code": "READ_MODEL_UNAVAILABLE",
                "message": "只读业务数据暂时不可用",
                "details": {"error_type": type(exc).__name__},
            },
            request_id=request_id,
        )

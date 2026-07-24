from __future__ import annotations

import traceback
import uuid
from typing import Any, Callable

from fastapi import APIRouter

from server.api.contracts import OperationRequest, OperationResponse
from server.api.serialization import decode_transport, encode_transport


def build_operation_router(
    *,
    prefix: str,
    tag: str,
    invoker: Callable[[str, list[Any], dict[str, Any]], Any],
    bootstrap: Callable[[], dict[str, Any]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    if bootstrap is not None:
        @router.get("/bootstrap", response_model=OperationResponse)
        def read_bootstrap() -> OperationResponse:
            request_id = uuid.uuid4().hex
            try:
                return OperationResponse(success=True, data=encode_transport(bootstrap()), request_id=request_id)
            except Exception as exc:
                return OperationResponse(
                    success=False,
                    error={
                        "code": type(exc).__name__,
                        "message": str(exc),
                        "details": {"traceback_tail": traceback.format_exc()[-4000:]},
                    },
                    request_id=request_id,
                )

    @router.post("/operations/{operation}", response_model=OperationResponse)
    def call_operation(operation: str, request: OperationRequest) -> OperationResponse:
        request_id = uuid.uuid4().hex
        try:
            args = decode_transport(request.args)
            kwargs = decode_transport(request.kwargs)
            result = invoker(str(operation), list(args or []), dict(kwargs or {}))
            return OperationResponse(success=True, data=encode_transport(result), request_id=request_id)
        except KeyError as exc:
            return OperationResponse(
                success=False,
                error={"code": "OPERATION_NOT_ALLOWED", "message": str(exc), "details": {}},
                request_id=request_id,
            )
        except Exception as exc:
            return OperationResponse(
                success=False,
                error={
                    "code": type(exc).__name__,
                    "message": str(exc),
                    "details": {"traceback_tail": traceback.format_exc()[-4000:]},
                },
                request_id=request_id,
            )

    return router

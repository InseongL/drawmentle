"""Common API error codes and the {"error": ..., "requestId": ...} response shape."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

log = logging.getLogger("drawmentle")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(code)
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = request.state.request_id = uuid.uuid4().hex
    return rid


def error_response(request: Request, status: int, code: str, message: str, retryable: bool) -> JSONResponse:
    rid = request_id(request)
    return JSONResponse(status_code=status, headers={"X-Request-Id": rid},
                        content={"error": {"code": code, "message": message, "retryable": retryable}, "requestId": rid})


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        rid = request_id(request)
        response = await call_next(request)
        response.headers.setdefault("X-Request-Id", rid)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo the submitted body (it may contain drawing data).
        top3 = any("top3" in [str(p) for p in err.get("loc", ())] for err in exc.errors())
        code = "INVALID_TOP3" if top3 else "INVALID_REQUEST"
        return error_response(request, 422, code, "요청 형식이 올바르지 않아요.", False)

    @app.exception_handler(OperationalError)
    async def db_unavailable(request: Request, exc: OperationalError):
        log.warning("database unavailable: %s", type(exc).__name__)
        return error_response(request, 503, "TEMPORARY_FAILURE", "잠시 후 다시 시도해주세요.", True)

    @app.exception_handler(IntegrityError)
    async def write_conflict(request: Request, exc: IntegrityError):
        # Only reachable if two writers bypassed the session lock; the same request ID can safely retry.
        log.warning("integrity conflict: %s", type(exc.orig).__name__)
        return error_response(request, 503, "TEMPORARY_FAILURE", "잠시 후 다시 시도해주세요.", True)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error")
        return error_response(request, 500, "INTERNAL_ERROR", "문제가 생겼어요. 잠시 후 다시 시도해주세요.", True)

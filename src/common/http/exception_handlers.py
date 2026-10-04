from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler as default_http_exception
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from common.errors import AppError, InvalidRequestBody, Unauthorized
from common.errors.standard_errors import (
    DatabaseFailure,
    Forbidden,
    InternalError,
    RouteNotFound,
)
from common.http.response_builders import api_error_response
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger(__name__)

API_PATH_PREFIX = "/api/"
REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})


def register_exception_handlers(app: FastAPI) -> None:
    """Give API failures the Problem Details shape clients already speak."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return api_error_response(exc, request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [
            {"field": _field_name(e["loc"]), "problem": _problem_text(e)} for e in exc.errors()
        ]
        detail = "; ".join(f"{f['field']}: {f['problem']}" for f in fields)
        return api_error_response(InvalidRequestBody(detail, fields), request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if not _is_api_request(request):
            # Re-raising escapes to ServerErrorMiddleware, which has no response
            # yet, so Uvicorn reports the miss as 500.
            return await default_http_exception(request, exc)
        return api_error_response(_app_error_for_status(exc.status_code, exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        if not _is_api_request(request):
            return PlainTextResponse("Internal Server Error", status_code=500)
        error = _to_app_error(exc)
        if error.status >= 500:
            logger.exception("Unhandled API exception")
        return api_error_response(error, request)


def _field_name(location: tuple) -> str:
    """``("body", "password")`` reads as ``password``; the request part is noise to a user."""
    parts = list(location)
    if len(parts) > 1 and parts[0] in REQUEST_PARTS:
        parts = parts[1:]
    return ".".join(str(part) for part in parts)


def _problem_text(error: dict) -> str:
    """A validator's own message, without pydantic's ``Value error,`` prefix."""
    cause = (error.get("ctx") or {}).get("error")
    if error.get("type") == "value_error" and cause is not None:
        return str(cause)
    return error["msg"]


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith(API_PATH_PREFIX)


def _to_app_error(exception: BaseException) -> AppError:
    if isinstance(exception, AppError):
        return exception
    if _is_database_error(exception):
        return DatabaseFailure(_public_detail(exception, DatabaseFailure.message))
    return InternalError(_public_detail(exception, InternalError.message))


def _app_error_for_status(status_code: int, detail: object = None) -> AppError:
    if status_code == 404:
        return RouteNotFound()
    if status_code == 401:
        return Unauthorized()
    if status_code == 403:
        return Forbidden()
    if status_code in (400, 422):
        message = detail if isinstance(detail, str) else None
        return InvalidRequestBody(message)
    return InternalError()


def _is_database_error(exception: BaseException) -> bool:
    name = type(exception).__name__
    return name in {"OperationalError", "DatabaseError", "InterfaceError"} or (
        exception.__class__.__module__.startswith("psycopg")
    )


def _public_detail(exception: BaseException, fallback: str) -> str:
    if not ActiveConfig.DEBUG:
        return fallback
    detail = str(exception).strip()
    return detail or fallback

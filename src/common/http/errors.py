from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from common.errors import AppError, InvalidRequestBody, Unauthorized
from common.errors.system import DatabaseFailure, Forbidden, InternalError, RouteNotFound
from common.http.request_response import api_error
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger(__name__)

API_PATH_PREFIX = "/api/"


def register_exception_handlers(app: FastAPI) -> None:
    """Give API failures the Problem Details shape clients already speak."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return api_error(exc, request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
            for e in exc.errors()
        ]
        detail = "; ".join(f"{f['field']}: {f['problem']}" for f in fields)
        return api_error(InvalidRequestBody(detail, fields), request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if not _is_api(request):
            raise exc
        return api_error(_from_status(exc.status_code, exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        if not _is_api(request):
            raise exc
        error = _classify(exc)
        if error.status >= 500:
            logger.exception("Unhandled API exception")
        return api_error(error, request)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith(API_PATH_PREFIX)


def _classify(exception: BaseException) -> AppError:
    if isinstance(exception, AppError):
        return exception
    if _is_database_error(exception):
        return DatabaseFailure(_public_detail(exception, DatabaseFailure.message))
    return InternalError(_public_detail(exception, InternalError.message))


def _from_status(status_code: int, detail: object = None) -> AppError:
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

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.enums.http_status import HttpStatus
from common.errors import AppError
from common.request_context import get_request_id
from common.schemas.pagination import PaginationMetadata
from common.schemas.responses import (
    APIResponse,
    FieldProblem,
    PaginatedAPIResponse,
    ProblemDetails,
)
from config import ActiveConfig

PROBLEM_CONTENT_TYPE = "application/problem+json"


def api_response(
    result: Any = None, status: HttpStatus = HttpStatus.OK
) -> JSONResponse:
    payload = APIResponse(result=serialize_for_json(result), status=int(status))
    return JSONResponse(payload.model_dump(mode="json"), status_code=int(status))


def api_paginated_response(
    items: list[Any],
    metadata: PaginationMetadata,
    status: HttpStatus = HttpStatus.OK,
) -> JSONResponse:
    payload = PaginatedAPIResponse(
        result=serialize_for_json(items), metadata=metadata, status=int(status)
    )
    return JSONResponse(payload.model_dump(mode="json"), status_code=int(status))


def api_error_response(error: AppError, request: Request | None = None) -> JSONResponse:
    base = ActiveConfig.BASE_URL.rstrip("/")
    subcode = getattr(error.error_subcode, "value", str(error.error_subcode))
    code = getattr(error.error_code, "value", str(error.error_code))

    field_errors: list[FieldProblem] | None = None
    if error.fields:
        field_errors = [FieldProblem.model_validate(f) for f in error.fields]

    payload = ProblemDetails(
        type=f"{base}/errors/{subcode.lower()}",
        title=error.problem_title(),
        status=int(error.status),
        detail=str(error),
        instance=request.url.path if request is not None else None,
        code=code,
        subcode=subcode,
        trace_id=get_request_id(request),
        errors=field_errors,
    )
    body = payload.model_dump(mode="json", exclude_none=True)
    response = JSONResponse(
        body, status_code=int(error.status), media_type=PROBLEM_CONTENT_TYPE
    )

    trace_id = body.get("trace_id")
    if trace_id:
        response.headers["X-Request-ID"] = trace_id

    retry_after = getattr(error, "retry_after", None)
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response


def serialize_for_json(result: Any) -> Any:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, (list, tuple)):
        return [serialize_for_json(item) for item in result]
    return result

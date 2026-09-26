from __future__ import annotations

from common.enums.error_codes import APIErrorCode
from common.enums.error_subcode import APIErrorSubCode
from common.enums.http_status import HttpStatus
from common.errors.app_error import AppError


class InvalidRequestBody(AppError):
    """The body did not match what the endpoint accepts."""

    error_code = APIErrorCode.VALIDATION
    error_subcode = APIErrorSubCode.BAD_DATA
    status = HttpStatus.UNPROCESSABLE_ENTITY
    title = "Validation failed"
    message = "The request body is not valid."

    def __init__(
        self, message: str | None = None, fields: list[dict] | None = None
    ) -> None:
        super().__init__(message, fields=fields or [])

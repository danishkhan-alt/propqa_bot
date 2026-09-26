from __future__ import annotations

from common.enums.error_codes import APIErrorCode
from common.enums.error_subcode import APIErrorSubCode
from common.enums.http_status import HttpStatus
from common.errors.app_error import AppError


class InternalError(AppError):
    error_code = APIErrorCode.SYSTEM
    error_subcode = APIErrorSubCode.INTERNAL_ERROR
    status = HttpStatus.INTERNAL_SERVER_ERROR
    title = "Internal error"
    message = "Something went wrong."


class DatabaseFailure(AppError):
    error_code = APIErrorCode.SYSTEM
    error_subcode = APIErrorSubCode.DATABASE_ERROR
    status = HttpStatus.INTERNAL_SERVER_ERROR
    title = "Database error"
    message = "A database error occurred."


class RouteNotFound(AppError):
    error_code = APIErrorCode.SYSTEM
    error_subcode = APIErrorSubCode.NOT_FOUND
    status = HttpStatus.NOT_FOUND
    title = "Not found"
    message = "This endpoint does not exist."


class ResourceNotFound(AppError):
    error_code = APIErrorCode.SYSTEM
    error_subcode = APIErrorSubCode.NOT_FOUND
    status = HttpStatus.NOT_FOUND
    title = "Not found"
    message = "That record does not exist."


class Forbidden(AppError):
    error_code = APIErrorCode.AUTH
    error_subcode = APIErrorSubCode.FORBIDDEN
    status = HttpStatus.FORBIDDEN
    title = "Access denied"
    message = "You are not allowed to do that."


class Unauthorized(AppError):
    error_code = APIErrorCode.AUTH
    error_subcode = APIErrorSubCode.UNAUTHORIZED
    status = HttpStatus.UNAUTHORIZED
    title = "Authentication required"
    message = "Sign in to continue."

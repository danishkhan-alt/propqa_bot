from __future__ import annotations

from common.enums.error_codes import APIErrorCode
from common.enums.error_subcode import APIErrorSubCode
from common.enums.http_status import HttpStatus
from common.errors.app_error import AppError


class EmailTaken(AppError):
    error_code = APIErrorCode.USER
    error_subcode = APIErrorSubCode.ALREADY_EXISTS
    status = HttpStatus.CONFLICT
    title = "Account exists"
    message = "An account with this email already exists."


class InvalidCredentials(AppError):
    error_code = APIErrorCode.AUTH
    error_subcode = APIErrorSubCode.UNAUTHORIZED
    status = HttpStatus.UNAUTHORIZED
    title = "Sign-in failed"
    message = "Incorrect email or password."


class InvalidToken(AppError):
    error_code = APIErrorCode.AUTH
    error_subcode = APIErrorSubCode.INVALID_TOKEN
    status = HttpStatus.UNAUTHORIZED
    title = "Authentication required"
    message = "Your session is not valid. Sign in again."


class TokenExpired(AppError):
    error_code = APIErrorCode.AUTH
    error_subcode = APIErrorSubCode.TOKEN_EXPIRED
    status = HttpStatus.UNAUTHORIZED
    title = "Authentication required"
    message = "Your session has expired. Sign in again."

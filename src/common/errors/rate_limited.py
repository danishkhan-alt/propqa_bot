from __future__ import annotations

from common.enums.error_codes import APIErrorCode
from common.enums.error_subcode import APIErrorSubCode
from common.enums.http_status import HttpStatus
from common.errors.exceptions import AppError


class RateLimited(AppError):
    """Too many attempts. Carries how long until the next one is worth making."""

    error_code = APIErrorCode.SYSTEM
    error_subcode = APIErrorSubCode.RATE_LIMITED
    status = HttpStatus.TOO_MANY_REQUESTS
    title = "Too many requests"
    message = "Too many attempts. Try again shortly."

    def __init__(self, retry_after: int = 60) -> None:
        #: Read by api_error to set the Retry-After header, so a client can
        #: wait exactly as long as it needs to instead of guessing.
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"Too many attempts. Try again in {self.retry_after} seconds.")

from __future__ import annotations

from common.enums.error_codes import APIErrorCode
from common.enums.error_subcode import APIErrorSubCode
from common.enums.http_status import HttpStatus

TITLE_BY_CODE: dict[APIErrorCode, str] = {
    APIErrorCode.VALIDATION: "Validation failed",
    APIErrorCode.AUTH: "Access denied",
    APIErrorCode.USER: "Account error",
    APIErrorCode.CHAT: "Chat error",
    APIErrorCode.AI: "AI error",
    APIErrorCode.SYSTEM: "Internal error",
}


class AppError(Exception):
    """A refusal the product intends, carrying its own API classification.

    Raised by services, so it must mean something with no request in sight:
    background jobs and agent tool calls reach services directly.
    """

    error_code: APIErrorCode = APIErrorCode.SYSTEM
    error_subcode: APIErrorSubCode = APIErrorSubCode.INTERNAL_ERROR
    status: HttpStatus = HttpStatus.INTERNAL_SERVER_ERROR
    message: str = "Something went wrong."
    title: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        fields: list[dict] | None = None,
    ) -> None:
        self.fields = fields
        super().__init__(message or self.message)

    def problem_title(self) -> str:
        if self.title:
            return self.title
        return TITLE_BY_CODE.get(self.error_code, "Request failed")

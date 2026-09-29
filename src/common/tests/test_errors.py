from __future__ import annotations

import json

from common.errors import InvalidRequestBody, RateLimited
from common.errors.standard_errors import InternalError
from common.http.response_builders import api_error_response


def test_api_error_is_problem_details():
    response = api_error_response(InvalidRequestBody("bad json"))
    body = json.loads(response.body)
    assert response.status_code == 422
    assert response.media_type == "application/problem+json"
    assert body["code"] == "VALIDATION"
    assert body["subcode"] == "BAD_DATA"
    assert body["detail"] == "bad json"


def test_rate_limited_sets_retry_after():
    response = api_error_response(RateLimited(12))
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"


def test_internal_error_has_system_codes():
    response = api_error_response(InternalError())
    body = json.loads(response.body)
    assert body["code"] == "SYSTEM"
    assert body["subcode"] == "INTERNAL_ERROR"
    assert body["status"] == 500

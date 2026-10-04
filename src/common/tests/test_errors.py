from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.errors import InvalidRequestBody, RateLimited
from common.errors.standard_errors import InternalError
from common.http.exception_handlers import register_exception_handlers
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


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("nope")

    @app.get("/api/boom")
    def api_boom() -> None:
        raise RuntimeError("nope")

    return app


def test_a_missing_page_is_404_not_500():
    client = TestClient(_app())
    missing = client.get("/")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}

    chrome = client.get("/json/version")
    assert chrome.status_code == 404


def test_a_missing_api_route_is_problem_details():
    response = TestClient(_app()).get("/api/missing")
    body = response.json()
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["subcode"] == "NOT_FOUND"
    assert body["detail"] == "This endpoint does not exist."


def test_a_non_api_crash_is_plain_500():
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"

    api = client.get("/api/boom")
    assert api.status_code == 500
    assert api.headers["content-type"].startswith("application/problem+json")
    assert api.json()["subcode"] == "INTERNAL_ERROR"

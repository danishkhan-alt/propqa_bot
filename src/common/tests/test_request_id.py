from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_a_plain_inbound_id_is_kept():
    response = _client().get("/ping", headers={REQUEST_ID_HEADER: "edge-7f3a.1"})
    assert response.headers[REQUEST_ID_HEADER] == "edge-7f3a.1"


def test_an_unsafe_inbound_id_is_replaced():
    for unsafe in ("has space", "x" * 129, "line\tbreak"):
        response = _client().get("/ping", headers={REQUEST_ID_HEADER: unsafe})
        assert response.headers[REQUEST_ID_HEADER] != unsafe
        assert response.headers[REQUEST_ID_HEADER]

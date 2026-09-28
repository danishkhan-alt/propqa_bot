"""Sign-up, sign-in, token rotation, and the bearer token making the caller registered."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import create_app
from auth import passwords, tokens
from auth.storage import InMemoryUserRepository
from auth.tokens import hash_refresh_token, issue_access_token
from common.cache import MemoryCache, set_cache
from common.services.app_clock import AppClock
from common.session import list_user_sessions, record_session_activity
from config import ActiveConfig, AppEnvironment

PASSWORD = "Str0ngPassword"
GUEST_ID = "anon-2b1c3f0e-8d4a-4c55-9a63-0d6c1f2e7b90"


@pytest.fixture(autouse=True)
def memory_cache():
    set_cache(MemoryCache())
    yield
    set_cache(None)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def repository() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def client(repository):
    app = create_app(user_repository=repository)

    @app.get("/api/test/caller")
    def caller(request: Request) -> dict:
        found = request.state.caller
        return {"kind": found.kind.value, "subject_id": found.subject_id}

    with TestClient(app) as test_client:
        yield test_client


def _register(client, email="Sara@Example.com", password=PASSWORD, **extra):
    body = {"name": "Sara Khan", "email": email, "password": password, **extra}
    return client.post("/api/auth/register", json=body)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_tokens_and_me_returns_the_user(client):
    response = _register(client, phone="  ")
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "sara@example.com"
    assert body["user"]["phone"] is None
    assert body["user"]["role"] == "user"
    assert body["access_token"] and body["refresh_token"]

    me = client.get("/api/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_only_a_hash_of_the_refresh_token_is_stored(client, repository):
    token = _register(client).json()["refresh_token"]
    assert token not in repository._tokens
    assert hash_refresh_token(token) in repository._tokens
    stored = repository.get_user_by_email("sara@example.com")
    assert PASSWORD not in stored.password_hash


def test_a_duplicate_email_is_a_conflict_whatever_its_case(client):
    assert _register(client).status_code == 201
    response = _register(client, email="  SARA@example.COM ")
    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists."


def test_sign_up_rules_match_the_form_and_read_plainly(client):
    cases = {
        "short1A": "password: Password must be at least 8 characters.",
        "lowercase1": "password: Password must contain at least one uppercase letter.",
        "NoDigitsHere": "password: Password must contain at least one number.",
    }
    for password, detail in cases.items():
        response = _register(client, password=password)
        assert response.status_code == 422
        assert response.json()["detail"] == detail

    response = _register(client, email="not-an-email")
    assert response.json()["detail"] == "email: Please enter a valid email."
    response = client.post("/api/auth/register", json={"email": "a@b.co", "password": PASSWORD})
    assert response.status_code == 422
    assert response.json()["detail"] == "name: Field required"


def test_login_accepts_the_right_password_only(client):
    _register(client)
    ok = client.post("/api/auth/login", json={"email": "SARA@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "sara@example.com"

    for email in ("sara@example.com", "nobody@example.com"):
        wrong = client.post("/api/auth/login", json={"email": email, "password": "Wrong-Pass1"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "Incorrect email or password."


def test_repeated_wrong_passwords_lock_the_account_for_a_while(client):
    _register(client)
    for _ in range(5):
        wrong = client.post("/api/auth/login", json={"email": "sara@example.com", "password": "Wrong-Pass1"})
        assert wrong.status_code == 401
    blocked = client.post("/api/auth/login", json={"email": "sara@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "Try again" in blocked.json()["detail"]


def test_refresh_rotates_and_the_old_token_stops_working(client):
    first = _register(client).json()
    rotated = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["user"] == first["user"]

    reused = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401
    assert isinstance(reused.json()["detail"], str)
    again = client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert again.status_code == 200


def test_logout_revokes_the_refresh_token(client):
    token = _register(client).json()["refresh_token"]
    assert client.post("/api/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_me_needs_a_valid_unexpired_token(client, repository):
    _register(client)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=_bearer("not.a.jwt")).status_code == 401

    user = repository.get_user_by_email("sara@example.com")
    stale = issue_access_token(
        user, now=AppClock.utcnow() - timedelta(seconds=ActiveConfig.JWT_ACCESS_TOKEN_TTL_SECONDS + 60)
    )
    expired = client.get("/api/auth/me", headers=_bearer(stale))
    assert expired.status_code == 401
    assert expired.json()["detail"] == "Your session has expired. Sign in again."


def test_a_bearer_token_makes_the_caller_registered(client):
    body = _register(client).json()
    registered = client.get("/api/test/caller", headers=_bearer(body["access_token"]))
    assert registered.json() == {"kind": "registered", "subject_id": body["user"]["id"]}
    assert "X-Visitor-ID" not in registered.headers


def test_a_bad_bearer_token_falls_back_to_a_visitor(client):
    response = client.get("/api/test/caller", headers=_bearer("garbage"))
    assert response.status_code == 200
    assert response.json()["kind"] == "visitor"


def test_claim_moves_a_guest_chat_into_the_account(client):
    body = _register(client).json()
    user_id = body["user"]["id"]
    record_session_activity(GUEST_ID, "thread1", "Villas in Arabian Ranches")

    assert client.post("/api/sessions/thread1/claim", json={"guest_user_id": GUEST_ID}).status_code == 401
    claim = client.post(
        "/api/sessions/thread1/claim",
        json={"guest_user_id": GUEST_ID, "merge_ltm": True},
        headers=_bearer(body["access_token"]),
    )
    assert claim.json() == {"status": "ok", "claimed": True}
    assert [row.session_id for row in list_user_sessions(user_id)] == ["thread1"]
    assert list_user_sessions(GUEST_ID) == []


def test_claim_cannot_take_another_accounts_chat(client):
    owner = _register(client, email="owner@example.com").json()["user"]["id"]
    thief = _register(client, email="thief@example.com").json()
    record_session_activity(owner, "thread2", "Hello")
    claim = client.post(
        "/api/sessions/thread2/claim",
        json={"guest_user_id": owner},
        headers=_bearer(thief["access_token"]),
    )
    assert claim.json()["claimed"] is False
    assert [row.session_id for row in list_user_sessions(owner)] == ["thread2"]


def test_a_deployed_app_will_not_start_without_a_strong_signing_key(monkeypatch):
    monkeypatch.setattr(tokens, "ENVIRONMENT", AppEnvironment.PRODUCTION)
    monkeypatch.setattr(ActiveConfig, "JWT_SIGNING_KEY", "")
    with pytest.raises(RuntimeError, match="JWT_SIGNING_KEY is required"):
        create_app()
    monkeypatch.setattr(ActiveConfig, "JWT_SIGNING_KEY", "short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        create_app()

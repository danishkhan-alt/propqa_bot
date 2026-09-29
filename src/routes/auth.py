"""Account routes the sign-up and sign-in forms call."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response

from auth import service
from auth.backends import get_user_repository
from auth.errors import InvalidCredentials
from auth.middleware import require_user_id
from auth.models import AuthSession
from auth.storage import UserRepository
from common.enums.http_status import HttpStatus
from common.ratelimit.declared import declare_rate_limits
from common.ratelimit.keys import ip_rate_limit_key
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import (
    REGISTER_ATTEMPTS,
    SIGN_IN_ACCOUNT,
    SIGN_IN_CALLER,
    TOKEN_REFRESH,
)
from config import ActiveConfig
from routes.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth")


@router.post("/register", status_code=int(HttpStatus.CREATED))
def register(request: Request, body: RegisterRequest) -> AuthResponse:
    limiter.enforce(ip_rate_limit_key(request), REGISTER_ATTEMPTS)
    session = service.register(
        _repository(request), email=body.email, name=body.name, password=body.password, phone=body.phone
    )
    return _auth_response(session)


@router.post("/login")
def login(request: Request, body: LoginRequest) -> AuthResponse:
    caller_key = ip_rate_limit_key(request)
    account_key = _account_rate_limit_key(body.email)
    limiter.enforce_without_counting(caller_key, *SIGN_IN_CALLER)
    limiter.enforce_without_counting(account_key, *SIGN_IN_ACCOUNT)
    try:
        session = service.sign_in(_repository(request), email=body.email, password=body.password)
    except InvalidCredentials:
        limiter.record(caller_key, *SIGN_IN_CALLER)
        limiter.record(account_key, *SIGN_IN_ACCOUNT)
        raise
    return _auth_response(session)


@router.post("/refresh")
def refresh(request: Request, body: RefreshTokenRequest) -> AuthResponse:
    limiter.enforce(ip_rate_limit_key(request), TOKEN_REFRESH)
    return _auth_response(service.refresh(_repository(request), body.refresh_token))


@router.post("/logout", status_code=int(HttpStatus.NO_CONTENT))
def logout(request: Request, body: RefreshTokenRequest) -> Response:
    service.sign_out(_repository(request), body.refresh_token)
    return Response(status_code=int(HttpStatus.NO_CONTENT))


@router.get("/me")
def me(request: Request) -> UserResponse:
    user = service.current_user(_repository(request), require_user_id(request))
    return UserResponse.from_record(user)


def _repository(request: Request) -> UserRepository:
    injected = getattr(request.app.state, "user_repository", None)
    if injected is not None:
        return injected
    return get_user_repository()


def _auth_response(session: AuthSession) -> AuthResponse:
    return AuthResponse.from_session(session, expires_in=ActiveConfig.JWT_ACCESS_TOKEN_TTL_SECONDS)


def _account_rate_limit_key(email: str) -> str:
    return f"account:{hashlib.sha256(email.encode('utf-8')).hexdigest()}"


for _view, _rules in (
    (register, (REGISTER_ATTEMPTS,)),
    (login, (*SIGN_IN_CALLER, *SIGN_IN_ACCOUNT)),
    (refresh, (TOKEN_REFRESH,)),
):
    declare_rate_limits(_view, *_rules)

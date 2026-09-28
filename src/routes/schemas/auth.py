"""Request and response bodies for the auth routes. Rules match the sign-up form."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

from auth.models import AuthSession, UserRecord, UserRole, normalize_email
from auth.passwords import MAX_PASSWORD_BYTES

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 100
EMAIL_MAX_LENGTH = 254
PASSWORD_MIN_LENGTH = 8
PHONE_MAX_LENGTH = 20
REFRESH_TOKEN_MAX_LENGTH = 256

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(value: str) -> str:
    email = normalize_email(value)
    if len(email) > EMAIL_MAX_LENGTH or not _EMAIL_PATTERN.match(email):
        raise ValueError("Please enter a valid email.")
    return email


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    email: str
    password: str
    phone: str | None = None

    @field_validator("name")
    @classmethod
    def name_is_sized(cls, value: str) -> str:
        name = " ".join(value.split())
        if len(name) < NAME_MIN_LENGTH:
            raise ValueError(f"Name must be at least {NAME_MIN_LENGTH} characters.")
        if len(name) > NAME_MAX_LENGTH:
            raise ValueError(f"Name must be at most {NAME_MAX_LENGTH} characters.")
        return name

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str) -> str:
        return _clean_email(value)

    @field_validator("password")
    @classmethod
    def password_is_strong(cls, value: str) -> str:
        if len(value) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} characters.")
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[0-9]", value):
            raise ValueError("Password must contain at least one number.")
        return value

    @field_validator("phone")
    @classmethod
    def phone_is_sized(cls, value: str | None) -> str | None:
        phone = (value or "").strip()
        if not phone:
            return None
        if len(phone) > PHONE_MAX_LENGTH:
            raise ValueError(f"Phone must be at most {PHONE_MAX_LENGTH} characters.")
        return phone


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str) -> str:
        return _clean_email(value)

    @field_validator("password")
    @classmethod
    def password_is_present(cls, value: str) -> str:
        if not value:
            raise ValueError("Enter your password.")
        return value


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def token_is_sized(cls, value: str) -> str:
        token = value.strip()
        if not token or len(token) > REFRESH_TOKEN_MAX_LENGTH:
            raise ValueError("Refresh token is not valid.")
        return token


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    phone: str | None
    role: UserRole

    @classmethod
    def from_record(cls, user: UserRecord) -> UserResponse:
        return cls(id=user.id, email=user.email, name=user.name, phone=user.phone, role=user.role)


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

    @classmethod
    def from_session(cls, session: AuthSession, expires_in: int) -> AuthResponse:
        return cls(
            user=UserResponse.from_record(session.user),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_in=expires_in,
        )

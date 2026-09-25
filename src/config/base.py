from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

load_dotenv(REPO_ROOT / ".env")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
load_dotenv(REPO_ROOT / f"{APP_ENV}.env")


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is AppEnvironment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self is AppEnvironment.DEVELOPMENT

    @property
    def is_test(self) -> bool:
        return self is AppEnvironment.TEST

    @property
    def is_deployed(self) -> bool:
        return self in (AppEnvironment.STAGING, AppEnvironment.PRODUCTION)


try:
    ENVIRONMENT = AppEnvironment(APP_ENV)
except ValueError:
    ENVIRONMENT = AppEnvironment.DEVELOPMENT


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


class Config:
    DEBUG = _bool("DEBUG", not ENVIRONMENT.is_deployed)
    ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")
    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = _int("APP_PORT", 8000)
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Dubai")

    # Warehouse the text-to-SQL tool reads. Credentials must stay read-only.
    AUDIT_DB_HOST = os.getenv("AUDIT_DB_HOST", "localhost")
    AUDIT_DB_PORT = _int("AUDIT_DB_PORT", 5432)
    AUDIT_DB_DATABASE = os.getenv("AUDIT_DB_DATABASE", "postgres")
    AUDIT_DB_USERNAME = os.getenv("AUDIT_DB_USERNAME", "")
    AUDIT_DB_PASSWORD = os.getenv("AUDIT_DB_PASSWORD", "")
    AUDIT_DB_SCHEMA = os.getenv("AUDIT_DB_SCHEMA", "public")
    DB_SEARCH_PATH = os.getenv("DB_SEARCH_PATH", "public")
    AUDIT_DB_SSLMODE = os.getenv(
        "AUDIT_DB_SSLMODE",
        "require" if ENVIRONMENT.is_deployed else "disable",
    )
    SQL_ROW_CAP = _int("SQL_ROW_CAP", 100)
    SQL_TIMEOUT_MS = _int("SQL_TIMEOUT_MS", 15_000)
    # Place names are matched inside this region of the location tree.
    GROUNDING_REGION = os.getenv("GROUNDING_REGION", "Dubai")
    GROUNDING_REFRESH_SECONDS = _int("GROUNDING_REFRESH_SECONDS", 3600)

    # Chatbot database on this machine's Postgres. The socket uses peer auth, so
    # the role matches the OS user and there is no password. Not the warehouse.
    CHAT_DB_HOST = os.getenv("CHAT_DB_HOST","localhost")
    CHAT_DB_PORT = _int("CHAT_DB_PORT", 5432)
    CHAT_DB_NAME = os.getenv("CHAT_DB_NAME", "propqa_chatbot")
    CHAT_DB_USER = os.getenv("CHAT_DB_USER", "" if ENVIRONMENT.is_deployed else os.getenv("USER", ""))
    CHAT_DB_PASSWORD = os.getenv("CHAT_DB_PASSWORD", "")
    CHAT_DB_SSLMODE = os.getenv("CHAT_DB_SSLMODE", "require" if ENVIRONMENT.is_deployed else "disable")
    CHAT_DB_POOL_MIN = _int("CHAT_DB_POOL_MIN", 1)
    CHAT_DB_POOL_MAX = _int("CHAT_DB_POOL_MAX", 10)

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TTL_SECONDS = _int("CACHE_TTL_SECONDS", 300)
    CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", f"propqa:{ENVIRONMENT.value}")

    JWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY", "")
    JWT_ISSUER = os.getenv("JWT_ISSUER", "propqa")
    JWT_ACCESS_TOKEN_TTL_SECONDS = _int("JWT_ACCESS_TOKEN_TTL_SECONDS", 900)
    JWT_REFRESH_TOKEN_TTL_DAYS = _int("JWT_REFRESH_TOKEN_TTL_DAYS", 30)

    # Which vendor serves every LLM call: "anthropic" or "openai".
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    LLM_MAX_OUTPUT_TOKENS = _int(
        "LLM_MAX_OUTPUT_TOKENS", _int("ANTHROPIC_MAX_OUTPUT_TOKENS", 4096)
    )
    AI_MODEL = os.getenv(
        "AI_MODEL", "gpt-4.1" if LLM_PROVIDER == "openai" else "claude-sonnet-5"
    )
    ROUTER_MODEL = os.getenv(
        "ROUTER_MODEL", "gpt-5.4-mini" if LLM_PROVIDER == "openai" else "claude-haiku-4-5"
    )
    # AI_MODEL reasons before it answers, and that reasoning counts against max_tokens.
    # Effort sets how much it reasons per route: replies write from facts already
    # fetched, SQL reasons. OpenAI routers reason too, so they get their own effort.
    AI_REPLY_EFFORT = os.getenv("AI_REPLY_EFFORT", "low")
    AI_SQL_EFFORT = os.getenv("AI_SQL_EFFORT", "medium")
    ROUTER_EFFORT = os.getenv("ROUTER_EFFORT", "low")

    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BASE_URL = os.getenv(
        "LANGFUSE_BASE_URL",
        os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )

    LOGS_DIR = os.getenv("LOGS_DIR", "logs")
    LOG_TO_FILE = _bool("LOG_TO_FILE", True)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_MAX_BYTES = _int("LOG_MAX_BYTES", 100 * 1024 * 1024)
    LOG_BACKUP_COUNT = _int("LOG_BACKUP_COUNT", 10)

    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    TRUSTED_PROXY_COUNT = _int("TRUSTED_PROXY_COUNT", 0)

    VISITOR_COOKIE_NAME = os.getenv("VISITOR_COOKIE_NAME", "propqa_visitor_id")
    VISITOR_COOKIE_MAX_AGE = _int("VISITOR_COOKIE_MAX_AGE", 60 * 60 * 24 * 365)


class DevelopmentConfig(Config):
    pass


class StagingConfig(Config):
    pass


class TestConfig(Config):
    DEBUG = True
    REDIS_URL = ""


class ProductionConfig(Config):
    DEBUG = False


CONFIG_MAPPING = {
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "test": TestConfig,
    "production": ProductionConfig,
}

ActiveConfig = CONFIG_MAPPING.get(APP_ENV, DevelopmentConfig)

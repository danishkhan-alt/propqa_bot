from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from config.enums import AppEnvironment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# .env only names the environment; <APP_ENV>.env holds its settings. Neither
# overrides a variable already set by the shell or by compose.
load_dotenv(REPO_ROOT / ".env")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
load_dotenv(REPO_ROOT / f"{APP_ENV}.env")


try:
    ENVIRONMENT = AppEnvironment(APP_ENV)
except ValueError:
    ENVIRONMENT = AppEnvironment.DEVELOPMENT


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


class Config:
    DEBUG = _env_bool("DEBUG", not ENVIRONMENT.is_deployed)
    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = _env_int("APP_PORT", 8000)
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Dubai")

    # Warehouse the text-to-SQL tool reads. Credentials must stay read-only.
    AUDIT_DB_HOST = os.getenv("AUDIT_DB_HOST", "localhost")
    AUDIT_DB_PORT = _env_int("AUDIT_DB_PORT", 5432)
    AUDIT_DB_DATABASE = os.getenv("AUDIT_DB_DATABASE", "postgres")
    AUDIT_DB_USERNAME = os.getenv("AUDIT_DB_USERNAME", "")
    AUDIT_DB_PASSWORD = os.getenv("AUDIT_DB_PASSWORD", "")
    DB_SEARCH_PATH = os.getenv("DB_SEARCH_PATH", "public")
    AUDIT_DB_SSLMODE = os.getenv(
        "AUDIT_DB_SSLMODE",
        "require" if ENVIRONMENT.is_deployed else "disable",
    )
    SQL_ROW_CAP = _env_int("SQL_ROW_CAP", 100)
    SQL_TIMEOUT_MS = _env_int("SQL_TIMEOUT_MS", 15_000)
    # Place names are matched inside this region of the location tree.
    GROUNDING_REGION = os.getenv("GROUNDING_REGION", "Dubai")
    GROUNDING_REFRESH_SECONDS = _env_int("GROUNDING_REFRESH_SECONDS", 3600)

    # Chatbot database on this machine's Postgres. The socket uses peer auth, so
    # the role matches the OS user and there is no password. Not the warehouse.
    CHAT_DB_HOST = os.getenv("CHAT_DB_HOST", "localhost")
    CHAT_DB_PORT = _env_int("CHAT_DB_PORT", 5432)
    CHAT_DB_NAME = os.getenv("CHAT_DB_NAME", "propqa_chatbot")
    CHAT_DB_USER = os.getenv(
        "CHAT_DB_USER", "" if ENVIRONMENT.is_deployed else os.getenv("USER", "")
    )
    CHAT_DB_PASSWORD = os.getenv("CHAT_DB_PASSWORD", "")
    CHAT_DB_SSLMODE = os.getenv(
        "CHAT_DB_SSLMODE", "require" if ENVIRONMENT.is_deployed else "disable"
    )
    CHAT_DB_POOL_MIN = _env_int("CHAT_DB_POOL_MIN", 1)
    CHAT_DB_POOL_MAX = _env_int("CHAT_DB_POOL_MAX", 10)

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", f"propqa:{ENVIRONMENT.value}")

    JWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY", "")
    JWT_ISSUER = os.getenv("JWT_ISSUER", "propqa")
    JWT_ACCESS_TOKEN_TTL_SECONDS = _env_int("JWT_ACCESS_TOKEN_TTL_SECONDS", 900)
    JWT_REFRESH_TOKEN_TTL_DAYS = _env_int("JWT_REFRESH_TOKEN_TTL_DAYS", 30)

    # Which vendor serves every LLM call: "anthropic" or "openai".
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    LLM_MAX_OUTPUT_TOKENS = _env_int("LLM_MAX_OUTPUT_TOKENS", 4096)
    AI_MODEL = os.getenv(
        "AI_MODEL", "gpt-4.1" if LLM_PROVIDER == "openai" else "claude-sonnet-5"
    )
    ROUTER_MODEL = os.getenv(
        "ROUTER_MODEL",
        "gpt-5.4-mini" if LLM_PROVIDER == "openai" else "claude-haiku-4-5",
    )

    AI_REPLY_EFFORT = os.getenv("AI_REPLY_EFFORT", "low")
    AI_SQL_EFFORT = os.getenv("AI_SQL_EFFORT", "medium")
    ROUTER_EFFORT = os.getenv("ROUTER_EFFORT", "low")

    JEV_API_KEY = os.getenv("JEV_API_KEY", "")
    JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
    JEV_TIMEOUT_MS = _env_int("JEV_TIMEOUT_MS", 4000)
    DOMAIN_ROUTER = (
        os.getenv("DOMAIN_ROUTER", "jev" if JEV_API_KEY else "llm").strip().lower()
    )

    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    # The Langfuse client reads these from the environment itself.
    LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    LOGS_DIR = os.getenv("LOGS_DIR", "logs")
    LOG_TO_FILE = _env_bool("LOG_TO_FILE", True)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_MAX_BYTES = _env_int("LOG_MAX_BYTES", 100 * 1024 * 1024)
    LOG_BACKUP_COUNT = _env_int("LOG_BACKUP_COUNT", 10)

    RATELIMIT_ENABLED = _env_bool("RATELIMIT_ENABLED", True)
    TRUSTED_PROXY_COUNT = _env_int("TRUSTED_PROXY_COUNT", 0)

    VISITOR_COOKIE_NAME = os.getenv("VISITOR_COOKIE_NAME", "propqa_visitor_id")
    VISITOR_COOKIE_MAX_AGE = _env_int("VISITOR_COOKIE_MAX_AGE", 60 * 60 * 24 * 365)


class DevelopmentConfig(Config):
    pass


class StagingConfig(Config):
    pass


class TestConfig(Config):
    DEBUG = True
    REDIS_URL = ""


class ProductionConfig(Config):
    DEBUG = False


CONFIG_BY_ENVIRONMENT = {
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "test": TestConfig,
    "production": ProductionConfig,
}

ActiveConfig = CONFIG_BY_ENVIRONMENT.get(APP_ENV, DevelopmentConfig)

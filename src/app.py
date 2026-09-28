"""Propqa HTTP app. Chat is a server-sent event stream."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.grounding import get_grounding_cache
from agent.memory.routes import router as memory_router
from auth.middleware import AuthMiddleware
from auth.tokens import signing_key
from common.http import register_exception_handlers
from common.logger import configure_logging
from common.middleware import CallerMiddleware, RateLimitMiddleware, RequestIdMiddleware
from common.middleware.rate_limit import DEFAULT_EXEMPT_PREFIXES
from config import ActiveConfig
from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.leads import router as leads_router
from routes.sessions import router as session_router

CORS_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def create_app(
    *,
    graph=None,
    models=None,
    sql_runner=None,
    listing_loader=None,
    listing_detail_loader=None,
    contact_loader=None,
    user_repository=None,
) -> FastAPI:
    # A deployed app without a usable JWT key must not start.
    signing_key()
    app = FastAPI(title="Propqa")
    app.state.chat_graph = graph
    app.state.chat_models = models
    app.state.sql_runner = sql_runner
    app.state.listing_loader = listing_loader
    app.state.listing_detail_loader = listing_detail_loader
    app.state.contact_loader = contact_loader
    app.state.user_repository = user_repository
    register_exception_handlers(app)
    app.include_router(auth_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(leads_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.add_middleware(
        RateLimitMiddleware, exempt_prefixes=(*DEFAULT_EXEMPT_PREFIXES, "/api/health")
    )
    app.add_middleware(CallerMiddleware)
    # Runs before CallerMiddleware: the last one added runs first.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/health")
    def api_health() -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "flags": {
                "ws_mounted": False,
                "hitl_transport": "sse",
                "cognitive_pipeline": False,
                "ltm_enabled": True,
            },
        }

    return app


def main() -> None:
    configure_logging(
        level=ActiveConfig.LOG_LEVEL,
        log_to_file=ActiveConfig.LOG_TO_FILE,
        logs_dir=ActiveConfig.LOGS_DIR,
        max_bytes=ActiveConfig.LOG_MAX_BYTES,
        backup_count=ActiveConfig.LOG_BACKUP_COUNT,
    )
    # Name grounding loads in the background; turns run without it until it is ready.
    get_grounding_cache().load_in_background()
    uvicorn.run(
        create_app(),
        host=ActiveConfig.APP_HOST,
        port=ActiveConfig.APP_PORT,
    )


if __name__ == "__main__":
    main()

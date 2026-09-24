"""Propqa HTTP app. Chat is a server-sent event stream."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.memory.routes import router as memory_router
from common.http import register_exception_handlers
from common.middleware import CallerMiddleware, RateLimitMiddleware, RequestIdMiddleware
from common.middleware.rate_limit import DEFAULT_EXEMPT_PREFIXES
from routes.chat import router as chat_router
from routes.sessions import router as session_router

_UI_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def create_app(*, graph=None, models=None, sql_runner=None) -> FastAPI:
    app = FastAPI(title="Propqa")
    app.state.chat_graph = graph
    app.state.chat_models = models
    app.state.sql_runner = sql_runner
    register_exception_handlers(app)
    app.include_router(chat_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.add_middleware(RateLimitMiddleware, exempt_prefixes=(*DEFAULT_EXEMPT_PREFIXES, "/api/health"))
    app.add_middleware(CallerMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_UI_ORIGINS),
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
    import uvicorn

    from common.logger import configure_logging
    from config import ActiveConfig

    configure_logging(
        level=ActiveConfig.LOG_LEVEL,
        log_to_file=ActiveConfig.LOG_TO_FILE,
        logs_dir=ActiveConfig.LOGS_DIR,
        max_bytes=ActiveConfig.LOG_MAX_BYTES,
        backup_count=ActiveConfig.LOG_BACKUP_COUNT,
    )
    uvicorn.run(
        create_app(),
        host=ActiveConfig.APP_HOST,
        port=ActiveConfig.APP_PORT,
    )


if __name__ == "__main__":
    main()

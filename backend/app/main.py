"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings
from app.db.session import dispose_engine, init_engine
from app.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        h.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://avatars.githubusercontent.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'",
        )
        if request.url.scheme == "https":
            h.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings = get_settings()
    configure_logging(settings)
    log.info("startup", env=settings.APP_ENV, org=settings.ALLOWED_ORG)
    init_engine(settings)
    try:
        yield
    finally:
        log.info("shutdown")
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Gitinho",
        version="0.1.0",
        description="Agente conversacional read-only para uma organização GitHub.",
        lifespan=lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    if settings.APP_ENV == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routers
    from app.api import auth_routes, chats, exports, health, messages, stream

    app.include_router(health.router)
    app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
    app.include_router(chats.router, prefix="/api/chats", tags=["chats"])
    app.include_router(messages.router, prefix="/api/chats", tags=["messages"])
    app.include_router(stream.router, prefix="/api/chats", tags=["stream"])
    app.include_router(exports.router, prefix="/api/exports", tags=["exports"])

    return app


app = create_app()

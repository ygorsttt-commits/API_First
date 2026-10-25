from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.auth_mode == "demo" and settings.app_env not in ("local", "test"):
        raise RuntimeError("AUTH_MODE=demo is only allowed with APP_ENV=local or test")

    app = FastAPI(title="AI Software Delivery Toolkit", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):  # never leak tracebacks or internals
        logging.getLogger("toolkit.api").exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.include_router(router)
    return app


app = create_app()

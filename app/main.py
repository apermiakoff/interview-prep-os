from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.db import init_db, transaction
from app.repository import seed_content


def trusted_hosts() -> list[str]:
    defaults = ["127.0.0.1", "localhost", "testserver"]
    configured = [
        host.strip()
        for host in os.getenv("INTERVIEW_PREP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]
    return [*defaults, *configured]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with transaction() as connection:
        seed_content(connection)
    yield


app = FastAPI(
    title="Interview Prep OS",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=trusted_hosts(),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(router)

static_dir = Path(
    os.getenv("INTERVIEW_PREP_STATIC", Path(__file__).parents[1] / "frontend" / "dist")
)
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
else:

    @app.get("/")
    def no_frontend() -> JSONResponse:
        return JSONResponse({"status": "api-ready", "frontend": "not-built"})

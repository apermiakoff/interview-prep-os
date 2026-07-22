from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.ai.ai_db import migrate as migrate_ai
from app.ai.api import router as ai_router
from app.api import router
from app.community import bootstrap_community
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


def allowed_origins() -> set[str]:
    return {
        value.strip().rstrip("/")
        for value in os.getenv("INTERVIEW_PREP_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    migrate_ai(Path(os.getenv("INTERVIEW_PREP_AI_DB", "/ai-data/interview-prep-ai.db")))
    with transaction() as connection:
        seed_content(connection)
        if os.getenv("INTERVIEW_PREP_BOOTSTRAP", "").lower() == "community":
            bootstrap_community(connection)
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
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", *allowed_origins()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """Block browser CSRF while retaining local CLI and health-check access."""
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        source = request.headers.get("origin")
        if source is None and request.headers.get("referer"):
            parsed = urlparse(request.headers["referer"])
            source = f"{parsed.scheme}://{parsed.netloc}"
        if source:
            expected = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
            accepted = {expected.rstrip("/"), *allowed_origins()}
            if source.rstrip("/") not in accepted:
                return JSONResponse({"detail": "cross-origin write rejected"}, status_code=403)
    return await call_next(request)


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
app.include_router(ai_router)

static_dir = Path(
    os.getenv("INTERVIEW_PREP_STATIC", Path(__file__).parents[1] / "frontend" / "dist")
)
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
else:

    @app.get("/")
    def no_frontend() -> JSONResponse:
        return JSONResponse({"status": "api-ready", "frontend": "not-built"})

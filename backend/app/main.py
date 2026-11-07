import base64
import hashlib
import re
import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import select
from starlette.middleware.base import RequestResponseEndpoint
import structlog

from app.core.config import settings
from app.core.db import dispose_engine, get_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestBodyLimitMiddleware
from app.core.redis import redis_client
from app.modules.auth.router import router as auth_router

configure_logging()
HTTP_REQUESTS = Counter("api_http_requests_total", "HTTP requests served", ["method", "status"])
HTTP_LATENCY = Histogram("api_http_request_duration_seconds", "HTTP request duration", ["method"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.validate_runtime()
    yield
    await redis_client.aclose()
    await dispose_engine()


app = FastAPI(title="VALORANT Strategy API", version="0.1.0", docs_url=None,
              redoc_url=None, openapi_url="/openapi.json" if settings.enable_docs else None, lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=bool(settings.cors_origins),
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
app.include_router(auth_router, prefix="/api/v1")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


if settings.enable_docs:
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui(request: Request) -> Response:
        root_path = request.scope.get("root_path", "").rstrip("/")
        assert app.openapi_url is not None
        static_url = f"{root_path}/static/swagger-ui"
        openapi_url = f"{root_path}{app.openapi_url}"
        oauth2_redirect_url = f"{root_path}{app.swagger_ui_oauth2_redirect_url}"
        response = get_swagger_ui_html(
            openapi_url=openapi_url,
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=oauth2_redirect_url,
            swagger_js_url=f"{static_url}/swagger-ui-bundle.js",
            swagger_css_url=f"{static_url}/swagger-ui.css",
            swagger_favicon_url=f"{static_url}/favicon-32x32.png",
            swagger_ui_parameters={"validatorUrl": None},
        )
        inline_scripts = re.findall(rb"<script(?:\s[^>]*)?>(.*?)</script>", response.body, re.DOTALL)
        inline_scripts = [script for script in inline_scripts if script.strip()]
        if len(inline_scripts) != 1:
            raise RuntimeError("Expected exactly one inline Swagger UI initialization script.")
        script_hash = base64.b64encode(hashlib.sha256(inline_scripts[0]).digest()).decode("ascii")
        request.state.docs_script_hash = script_hash
        return response

    @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect() -> Response:
        return get_swagger_ui_oauth2_redirect_html()


@app.middleware("http")
async def hardening(request: Request, call_next: RequestResponseEndpoint) -> Response:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_request_bytes:
                return JSONResponse(status_code=413, content={"error": {"code": "payload_too_large", "message": "Request body is too large"}})
        except ValueError:
            return JSONResponse(status_code=400, content={"error": {"code": "invalid_content_length", "message": "Invalid request"}})
    requested_id = request.headers.get("x-request-id", "")
    request_id = requested_id if _REQUEST_ID.fullmatch(requested_id) else str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        HTTP_REQUESTS.labels(request.method, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method).observe(time.perf_counter() - started)
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if hasattr(request.state, "docs_script_hash"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src 'self' 'sha256-{request.state.docs_script_hash}'; "
            "style-src 'self'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_bytes)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(select(1))
        await redis_client.ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready"})


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

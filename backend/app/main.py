"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.router import limiter
from app.core.auth.router import router as auth_router
from app.core.license.router import router as license_router
from app.core.license.service import license_manager
from app.core.log_context import (
    new_request_id,
    reset_request_context,
    set_request_context,
    setup_logging,
)
from app.core.plugins.loader import load_modules
from app.core.plugins.processor import PendingProcessor
from app.core.plugins.service import ModuleService
from app.core.scheduler import init_scheduler, shutdown_scheduler
from app.core.schemas import ErrorResponse
from app.database import async_session_maker, engine, get_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown."""
    setup_logging()

    load_modules(app)

    # Multi-tenant foundation: guarantee the default tenant exists and
    # every clinic is owned by it (idempotent upgrade path), then expose
    # the resolver + engine registry on app.state for middleware/jobs.
    try:
        from app.core.tenancy.bootstrap import ensure_default_tenant
        from app.core.tenancy.lifespan import build_engine_registry, build_resolver

        await ensure_default_tenant()
        app.state.tenant_resolver = build_resolver()
        app.state.tenant_engines = build_engine_registry()
    except Exception:
        logger.exception("Tenancy bootstrap failed at startup")
        raise

    try:
        async with async_session_maker() as session:
            await ModuleService(session).reconcile_with_db()
    except Exception:
        logger.exception("Module registry reconciliation failed at startup")

    try:
        processor = PendingProcessor(async_session_maker)
        processed = await processor.run()
        if processed:
            logger.info("Processed pending module operations: %s", processed)
    except Exception:
        logger.exception("Pending module processor raised")

    init_scheduler()

    yield

    shutdown_scheduler()
    engines = getattr(app.state, "tenant_engines", None)
    if engines is not None:
        await engines.dispose_all()
    await engine.dispose()


app = FastAPI(
    title="Dentora API",
    description="Open source dental clinic management software",
    version="2.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

allowed_origins = settings.allowed_origins_list.copy()
if settings.ENVIRONMENT == "development":
    allowed_origins.extend(
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Bind ``request_id`` for the lifetime of one HTTP request."""
    incoming = request.headers.get("x-request-id")
    rid = incoming if incoming and len(incoming) <= 64 else new_request_id()
    tokens = set_request_context(request_id=rid)
    try:
        response = await call_next(request)
    finally:
        reset_request_context(tokens)
    response.headers["X-Request-Id"] = rid
    return response


@app.middleware("http")
async def commercial_license_middleware(request: Request, call_next):
    """Block paid local installations until a signed license lease is active.

    Hosted/dev deployments are unaffected because LICENSE_ENFORCEMENT defaults
    to false. The activation endpoints remain reachable while locked.
    """
    if settings.LICENSE_ENFORCEMENT and request.url.path.startswith("/api/v1"):
        allowed_prefixes = ("/api/v1/license/",)
        if not request.url.path.startswith(allowed_prefixes):
            license_status = await license_manager.get_status(allow_refresh=True)
            if not license_status.get("active"):
                message = license_status.get("reason") or "Dentora license activation required"
                error_response = ErrorResponse(message=message, errors=[message])
                return JSONResponse(
                    status_code=402,
                    content=error_response.model_dump(),
                )
    return await call_next(request)


def _cors_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origin in allowed_origins or "*" in allowed_origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handler for HTTP exceptions using standard ErrorResponse format."""
    error_response = ErrorResponse(
        message=str(exc.detail),
        errors=[str(exc.detail)] if exc.detail else [],
    )
    headers = dict(exc.headers or {})
    headers.update(_cors_headers(request))
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(),
        headers=headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for unhandled exceptions."""
    logger.exception("Unhandled exception", exc_info=exc)
    if settings.ENVIRONMENT == "development":
        error_response = ErrorResponse(
            message=str(exc),
            errors=[str(exc)],
        )
    else:
        error_response = ErrorResponse(
            message="Internal server error",
            errors=[],
        )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump(),
        headers=_cors_headers(request),
    )


# License endpoints must be mounted before normal first-run/auth flows so a
# locked commercial installation can always be activated.
app.include_router(license_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")

from app.core.plugins.router import router as modules_router  # noqa: E402

app.include_router(modules_router, prefix="/api/v1")

from app.core.agents.router import router as agents_router  # noqa: E402

app.include_router(agents_router, prefix="/api/v1")

from app.core.tenancy.platform_router import router as platform_router  # noqa: E402

app.include_router(platform_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> JSONResponse:
    """Liveness probe — process is up."""
    return JSONResponse(content={"status": "healthy", "version": "2.0.0"})


@app.get("/health/ready")
async def readiness_check(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Readiness probe — schema is reachable."""
    try:
        await db.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "version": "2.0.0", "error": str(exc)},
        )
    return JSONResponse(content={"status": "ready", "version": "2.0.0"})


@app.get("/api/v1")
async def api_root() -> dict:
    """API root endpoint."""
    return {
        "message": "Dentora API",
        "version": "2.0.0",
        "docs": "/docs" if settings.ENVIRONMENT == "development" else None,
    }

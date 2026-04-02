import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.dependencies import get_stock_agent
from app.core.logging import configure_logging
from app.core.rate_limiter import RateLimitMiddleware
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.settings import get_settings
from app.db import models  # noqa: F401 - ensure models are imported for metadata
from app.db.session import Base, engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        get_stock_agent()
    except Exception:
        logger.warning("Service warm-up failed during startup.", exc_info=True)
    logger.info("Application startup complete.")
    try:
        yield
    finally:
        logger.info("Application shutdown complete.")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(router, prefix=settings.api_prefix)


@app.on_event("startup")
def create_tables() -> None:
    """Ensure all database tables exist before handling requests."""
    Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {"name": settings.app_name, "docs": "/docs", "api_prefix": settings.api_prefix}

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # Let API routes 404 normally; only handle non-API paths for SPA
    if full_path.startswith(settings.api_prefix.lstrip("/")):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if os.path.isdir(static_dir):
        index_path = os.path.join(static_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    logger.exception("Unhandled application error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error."})

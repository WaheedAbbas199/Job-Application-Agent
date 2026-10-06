"""Application factory: middleware, error handlers, routers, static frontend."""
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import (agents, analytics, applications, auth, documents, interviews, jobs, matches,
                        notifications, profile, resumes)
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, log, setup_logging, trace_id_var
from app.core.ratelimit import RateLimiter
from app.db.session import engine

logger = get_logger("app")
STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    limiter = RateLimiter()

    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        tid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        trace_id_var.set(tid)
        path = request.url.path
        if path.startswith("/api/"):
            ip = request.client.host if request.client else "?"
            strict = path in ("/api/v1/auth/login", "/api/v1/auth/register")
            limit = s.auth_rate_limit_per_minute if strict else s.rate_limit_per_minute
            if not limiter.allow(f"{ip}:{'auth' if strict else 'api'}", limit):
                return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests"}},
                                    status_code=429, headers={"Retry-After": "60"})
        t0 = time.monotonic()
        response = await call_next(request)
        response.headers.update({
            "X-Request-ID": tid, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer", "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
                                       if not path.startswith("/api/docs") else "",
        })
        if s.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        log(logger, 20, "request", method=request.method, path=path, status=response.status_code,
            ms=round((time.monotonic() - t0) * 1000, 1))
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Invalid request", "details": details}},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail)}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")  # details stay in logs only
        return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong"}}, status_code=500)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready():
        checks = {}
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        if s.redis_url:
            try:
                import redis
                redis.Redis.from_url(s.redis_url, socket_timeout=1).ping()
                checks["redis"] = "ok"
            except Exception:
                checks["redis"] = "unavailable"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    for r in (auth, profile, resumes, jobs, matches, applications, documents, interviews, analytics,
              notifications, agents):
        app.include_router(r.router, prefix="/api/v1")

    if STATIC.exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()

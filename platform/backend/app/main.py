"""FastAPI application factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.api.v1.router import api_router
from app.utils.log_scrub import install_root_scrubber

settings = get_settings()

# Install the secret-scrubbing logging filter before any app logger emits
# its first record. The filter redacts `sk-ant-…` and a handful of other
# credential shapes from every `LogRecord` (msg, args, exc_text) so an
# accidentally-logged raw key never reaches stdout / a file handler /
# structured log output. Pydantic's `SecretStr` on `settings.anthropic_
# api_key` is the primary defense; this is belt-and-suspenders for the
# path where a third-party SDK exception or a future bug materialises
# the raw value. Idempotent — re-running at import is a no-op.
install_root_scrubber()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Job Aggregator Platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# ── Security headers ─────────────────────────────────────────────────────
# Baseline response hardening. The regression tester flagged (finding 19)
# that prod responses were missing CSP/HSTS/Permissions-Policy/cross-origin
# headers. We apply a conservative set on every response. We deliberately
# DO NOT set a strict CSP on HTML routes yet (the frontend is served from
# a separate origin/container and the SPA bundle's build hashes rotate),
# but we do set headers that are safe for JSON APIs. HSTS is only meaningful
# under HTTPS; a reverse proxy would normally add it, but including it here
# defends against misconfigured termination.
#
# Regression finding 219: X-Frame-Options, X-Content-Type-Options, and
# Referrer-Policy are ALSO emitted by the outer infra nginx at the http
# block (`infra/nginx/nginx.conf:40-43`). nginx's `add_header` does NOT
# replace headers present in the upstream response — it APPENDS — so
# every API response was shipping two copies, one of them conflicting
# (FastAPI "X-Frame-Options: DENY" vs nginx "X-Frame-Options: SAMEORIGIN").
# Per RFC 7034 + MDN, browsers differ on multi-valued XFO: Chrome picks
# the strictest, Firefox ignores both, Safari undocumented — so the same
# app served different clickjacking protections to different users.
#
# Canonical choice per the finding: the infra nginx layer owns XFO /
# XCTO / Referrer-Policy because those headers survive even if the
# backend container crashes or is replaced with a static error page.
# We KEEP HSTS, Permissions-Policy, COOP, CORP, CSP in FastAPI because
# nginx does not set those; they would disappear on header-dedupe
# without this middleware. In the same round, nginx.conf's XFO value
# changes SAMEORIGIN → DENY to align with the CSP `frame-ancestors
# 'none'` intent ("nobody can frame us"), removing the stale
# same-origin-framing policy ambiguity.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    # A conservative CSP suitable for JSON API responses. The SPA that
    # renders HTML is served separately by nginx with its own CSP.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            # Don't stomp a header that an endpoint set intentionally.
            response.headers.setdefault(name, value)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Session middleware for OAuth state
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret, session_cookie="oauth_state")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
